"""The experimentalist for DiscoveryWorld: runs one laboratory packet inside the environment.

Auctopus starts it as the lab agent (`lab.agent = "custom"`) in the laboratory's exchange root, with the run packet in
inbox/<run-id>/. It plays the DiscoveryWorld scenario step by step with a model (observation in, one JSON action out,
like the paper's Hypothesizer baseline), guided by the packet's protocol, and returns:

    outbox/<run-id>/data/trajectory.jsonl   one record per step: observation summary, action, result
    outbox/<run-id>/data/notes.md           the agent's running memory and hypotheses
    outbox/<run-id>/data/final_knowledge.md the agent's final statement of what it learned
    outbox/<run-id>/deviations.md
    outbox/<run-id>/RUN-RESULT.json         status done | failed
    scores/<run-id>.json                    the environment's oracle scorecard (kept out of the outbox so that
                                            neither the experimentalist nor the researcher sees it)

    python -m auctopus.bench.dw_agent --prompt .auctopus/prompts/lab-<run-id>.md --model gpt-5-nano
        --scenario "Plant Nutrients" --difficulty Easy --seed 0 --steps 100 --dw-root <discoveryworld checkout>

`--model mock` plays a few random valid moves (or writes stand-in files when the environment is not importable).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

SYSTEM = """You are the experimentalist of an autonomous research laboratory, operating a scientific-discovery
simulation (DiscoveryWorld: a 2D top-down world with rooms, objects, instruments and other characters). A run
packet from the principal investigator tells you the hypothesis under test, the protocol to follow and the data to
return. Follow the protocol as far as the environment allows, record what you observe, and never invent
observations.

Each step you receive the current observation and must answer with ONE JSON object:
{"action": "<ACTION NAME>", "arg1": <uuid, direction string, location name, post id or null>, "arg2": <uuid or null>,
 "protocol_step": "<which protocol step this serves>", "explanation": "<one or two sentences>",
 "memory": "<notes to your future self: results so far, what worked, what to do next>",
 "running_hypotheses": "<your current hypotheses and the evidence for or against each>"}
When the observation shows a dialog box, answer instead with {"chosen_dialog_option_int": <int>, "memory": "...",
"running_hypotheses": "..."}.

Rules of the world
- You can interact only with objects in your inventory or directly in front of you (one tile, the direction you face).
- TELEPORT_TO_OBJECT with an object's uuid is the fastest way to reach anything, including objects you cannot see;
  TELEPORT_TO_LOCATION takes a location name from the list.
- MOVE_DIRECTION and ROTATE_DIRECTION take "north", "east", "south" or "west" as arg1.
- Instruments are used with USE: arg1 = instrument uuid, arg2 = target uuid. Read the lastActionMessage: it holds
  the measurement.
- If an action failed, understand why before repeating it.
"""


def stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------ observation summary

def summarize_observation(obs: dict, api) -> dict:
    ui = obs.get("ui", {})
    nearby = {}
    nb = ui.get("nearbyObjects") or {}
    for direction, objs in (nb.get("objects") or {}).items():
        rows = []
        for o in objs or []:
            if isinstance(o, dict):
                rows.append(f"{o.get('name')} [{o.get('uuid')}]" + (f" d={o.get('distance')}"
                                                                     if o.get("distance") is not None else ""))
        if rows:
            nearby[direction] = rows[:25]
    acc = [{"uuid": o.get("uuid"), "name": o.get("name"), "description": (o.get("description") or "")[:160]}
           for o in ui.get("accessibleEnvironmentObjects") or []]
    inv = [{"uuid": o.get("uuid"), "name": o.get("name"), "description": (o.get("description") or "")[:160]}
           for o in ui.get("inventoryObjects") or []]
    task = ui.get("taskProgress") or []
    out = {
        "world_steps": ui.get("world_steps"),
        "task": [{"description": t.get("description"), "completed": t.get("completed")} for t in task],
        "location": ui.get("agentLocation"),
        "lastActionMessage": ui.get("lastActionMessage"),
        "extended_action_message": ui.get("extended_action_message"),
        "accessible_objects_in_front_or_inventory": acc,
        "inventory": inv,
        "nearby_objects_by_direction": nearby,
        "nearby_agents": ui.get("nearbyAgents"),
        "discovery_feed": ui.get("discoveryFeed"),
    }
    if ui.get("dialog_box") and (ui["dialog_box"].get("dialogIn") or ui["dialog_box"].get("dialogOptions")):
        out["dialog_box"] = ui["dialog_box"]
    try:
        out["teleport_locations"] = list(api.listTeleportLocationsDict().keys())
    except Exception:  # noqa: BLE001
        out["teleport_locations"] = []
    return out


def parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts[1::2]:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:]
            try:
                return json.loads(p)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def coerce_arg(v):
    if v is None or isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return v


# ----------------------------------------------------------------------------------------------------- policies

class ModelPolicy:
    def __init__(self, model: str, effort: str):
        import openai
        self.client = openai.OpenAI(max_retries=2, timeout=300)
        self.model = model
        self.effort = effort
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def ask(self, prompt: str, json_mode: bool = True) -> str:
        kwargs = dict(model=self.model, messages=[{"role": "system", "content": SYSTEM},
                                                 {"role": "user", "content": prompt}],
                      max_completion_tokens=2500)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.effort:
            kwargs["reasoning_effort"] = self.effort
        delays = [10, 30, 60]
        for attempt in range(len(delays) + 1):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == len(delays):
                    raise
                print(f"dw_agent: API error ({e}); retry in {delays[attempt]} s", flush=True)
                time.sleep(delays[attempt])
        u = resp.usage
        self.usage["calls"] += 1
        self.usage["input_tokens"] += int(getattr(u, "prompt_tokens", 0) or 0)
        self.usage["output_tokens"] += int(getattr(u, "completion_tokens", 0) or 0)
        return resp.choices[0].message.content or ""


class MockPolicy:
    """Random valid moves with scripted notes (offline smoke tests)."""

    def __init__(self):
        self.r = random.Random(0)
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def ask(self, prompt: str, json_mode: bool = True) -> str:
        if "FINAL KNOWLEDGE" in prompt:
            return "Mock knowledge: the experimentalist moved around and used the instrument once."
        try:
            obs = json.loads(prompt.split("OBSERVATION:\n", 1)[1].split("\nPROTOCOL", 1)[0])
        except Exception:  # noqa: BLE001
            obs = {}
        if obs.get("dialog_box"):
            return json.dumps({"chosen_dialog_option_int": 1, "memory": "mock", "running_hypotheses": "mock"})
        acc = obs.get("accessible_objects_in_front_or_inventory") or []
        if acc and self.r.random() < 0.3:
            return json.dumps({"action": "PICKUP", "arg1": acc[0]["uuid"], "arg2": None, "protocol_step": "1",
                               "explanation": "mock", "memory": "mock memory", "running_hypotheses": "H1"})
        return json.dumps({"action": "MOVE_DIRECTION", "arg1": self.r.choice(["north", "east", "south", "west"]),
                           "arg2": None, "protocol_step": "1", "explanation": "mock", "memory": "mock memory",
                           "running_hypotheses": "H1"})


# ------------------------------------------------------------------------------------------------------- episode

def read_packet(inbox: Path) -> str:
    parts = []
    for name in ("README.md", "protocol.md", "results_schema.md"):
        p = inbox / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            parts.append(f"----- {name} -----\n{text[:12000]}")
    return "\n\n".join(parts) or "(no packet documents found)"


def play(api, policy, packet_text: str, max_steps: int, log, trajectory_path: Path) -> dict:
    """The step loop. Returns the final memory, hypotheses, counts and the action history."""
    memory, hypotheses = "", ""
    history: list[dict] = []
    failures = 0
    with open(trajectory_path, "w", encoding="utf-8") as traj:
        for step in range(1, max_steps + 1):
            with contextlib.redirect_stdout(log):
                obs = api.getAgentObservation(agentIdx=0)
                in_dialog = api.isAgentInDialog(agentIdx=0)
                actions = api.listKnownActions(limited=False)
            summary = summarize_observation(obs, api)
            recent = history[-5:]
            prompt = (f"STEP {step} of {max_steps}.\n\nOBSERVATION:\n{json.dumps(summary, ensure_ascii=False)}\n"
                      f"\nPROTOCOL AND PACKET:\n{packet_text}\n\nAVAILABLE ACTIONS:\n"
                      f"{json.dumps(actions)}\n\nRECENT ACTIONS AND RESULTS:\n"
                      f"{json.dumps(recent, ensure_ascii=False)}\n\nYOUR MEMORY:\n{memory or '(empty)'}\n\n"
                      f"YOUR RUNNING HYPOTHESES:\n{hypotheses or '(none yet)'}\n\n"
                      + ("The agent is IN A DIALOG: answer with chosen_dialog_option_int.\n" if in_dialog else "")
                      + "Reply with the single JSON object described in your instructions.")
            reply = policy.ask(prompt)
            decision = parse_json(reply) or {}
            memory = str(decision.get("memory") or memory)
            hypotheses = str(decision.get("running_hypotheses") or hypotheses)
            if in_dialog or "chosen_dialog_option_int" in decision:
                opt = decision.get("chosen_dialog_option_int", 1)
                try:
                    opt = int(opt)
                except (TypeError, ValueError):
                    opt = 1
                action = {"chosen_dialog_option_int": opt}
            else:
                action = {"action": str(decision.get("action") or "MOVE_DIRECTION"),
                          "arg1": coerce_arg(decision.get("arg1")), "arg2": coerce_arg(decision.get("arg2"))}
            with contextlib.redirect_stdout(log):
                try:
                    result = api.performAgentAction(agentIdx=0, actionJSON=action)
                except Exception as e:  # noqa: BLE001 - the environment is not always robust to odd arguments
                    result = {"success": False, "errors": [f"{type(e).__name__}: {e}"]}
                api.tick()
                after = api.getAgentObservation(agentIdx=0)
                complete = api.areTasksComplete()
            msg = (after.get("ui", {}) or {}).get("lastActionMessage")
            ok = bool(result.get("success")) if isinstance(result, dict) else False
            failures = 0 if ok else failures + 1
            record = {"step": step, "action": action, "success": ok,
                      "errors": (result.get("errors") if isinstance(result, dict) else None),
                      "result_message": msg, "protocol_step": decision.get("protocol_step"),
                      "explanation": decision.get("explanation")}
            history.append(record)
            traj.write(json.dumps({**record, "observation": summary, "memory": memory,
                                   "running_hypotheses": hypotheses}, ensure_ascii=False) + "\n")
            traj.flush()
            print(f"dw_agent[{step}]: {json.dumps(action)} -> {'ok' if ok else 'FAILED'}: {str(msg)[:120]}",
                  flush=True)
            if complete:
                print("dw_agent: the environment reports the task complete", flush=True)
                break
    return {"memory": memory, "hypotheses": hypotheses, "steps": len(history),
            "successful_actions": sum(1 for h in history if h["success"]), "history": history}


def final_knowledge(policy, task_desc: str, outcome: dict) -> str:
    prompt = (f"FINAL KNOWLEDGE REPORT.\n\nTask: {task_desc}\n\nYour final memory:\n{outcome['memory']}\n\n"
              f"Your running hypotheses:\n{outcome['hypotheses']}\n\nLast actions:\n"
              f"{json.dumps(outcome['history'][-15:], ensure_ascii=False)}\n\n"
              "Write, in plain prose (not JSON), what you now know about the scientific question of the task: the "
              "measurements you made, the hypothesis the evidence supports, the hypotheses it rules out, and what "
              "remains uncertain. State the answer to the task explicitly if you reached one. Do not invent "
              "measurements you did not make.")
    return policy.ask(prompt, json_mode=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="DiscoveryWorld experimentalist for Auctopus")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--model", default="gpt-5-nano")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--difficulty", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=100)
    ap.add_argument("--dw-root", required=True, help="the discoveryworld checkout (added to sys.path)")
    a = ap.parse_args()
    root = Path.cwd().resolve()
    job_id = Path(a.prompt).stem
    if not job_id.startswith("lab-"):
        print(f"dw_agent: job {job_id} is not a laboratory run (lab-<run-id>)", file=sys.stderr)
        return 2
    run_id = job_id[len("lab-"):]
    inbox, outbox = root / "inbox" / run_id, root / "outbox" / run_id
    scores = root / "scores"
    (outbox / "data").mkdir(parents=True, exist_ok=True)
    scores.mkdir(exist_ok=True)
    packet_text = read_packet(inbox)
    started = stamp()
    status, notes, deviations = "done", "", "none"
    usage = {}
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    sys.path.insert(0, str(Path(a.dw_root).resolve()))
    try:
        env_ok = True
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                from discoveryworld.DiscoveryWorldAPI import DiscoveryWorldAPI
        except Exception as e:  # noqa: BLE001
            env_ok = False
            if a.model != "mock":
                raise RuntimeError(f"cannot import discoveryworld from {a.dw_root}: {e}") from e
        policy = MockPolicy() if a.model == "mock" else ModelPolicy(a.model, a.effort)
        log = open(outbox / "data" / "environment.log", "w", encoding="utf-8")
        if env_ok:
            cwd = os.getcwd()
            os.chdir(a.dw_root)            # the environment loads its assets relative to its checkout
            try:
                with contextlib.redirect_stdout(log):
                    api = DiscoveryWorldAPI(threadID=int(time.time() * 1000) % 10_000_000)
                    ok = api.loadScenario(scenarioName=a.scenario, difficultyStr=a.difficulty, randomSeed=a.seed,
                                          numUserAgents=1)
                if not ok:
                    raise RuntimeError(f"could not load scenario {a.scenario!r} / {a.difficulty!r}")
                with contextlib.redirect_stdout(log):
                    card = api.getTaskScorecard()
                task_desc = card[0]["taskDescription"] if card else ""
                steps = 5 if a.model == "mock" else a.steps
                outcome = play(api, policy, packet_text, steps, log, outbox / "data" / "trajectory.jsonl")
                knowledge = final_knowledge(policy, task_desc, outcome)
                with contextlib.redirect_stdout(log):
                    card = api.getTaskScorecard()
                oracle = {"run_id": run_id, "scenario": a.scenario, "difficulty": a.difficulty, "seed": a.seed,
                          "steps_taken": outcome["steps"], "step_budget": steps,
                          "scorecard": card, "finished": stamp()}
                (scores / f"{run_id}.json").write_text(json.dumps(oracle, indent=1, ensure_ascii=False),
                                                       encoding="utf-8")
                notes = (f"{outcome['steps']} steps taken of {steps}; {outcome['successful_actions']} actions "
                         f"succeeded; task reported complete: {bool(card and card[0].get('completed'))}")
                if outcome["steps"] < steps and not (card and card[0].get("completed")):
                    deviations = "the run ended before the step budget without task completion; see deviations.md"
            finally:
                os.chdir(cwd)
        else:
            # mock without the environment: stand-in files so the pipeline downstream has something to analyse
            outcome = {"memory": "mock", "hypotheses": "mock", "steps": 0, "successful_actions": 0, "history": []}
            knowledge = "Mock knowledge (environment not importable)."
            (outbox / "data" / "trajectory.jsonl").write_text("")
            (scores / f"{run_id}.json").write_text(json.dumps({"run_id": run_id, "scorecard": None,
                                                               "note": "environment not importable"}))
            notes = "mock run without the environment"
        log.close()
        (outbox / "data" / "notes.md").write_text(f"# Experimentalist notes\n\n## Memory\n{outcome['memory']}\n\n"
                                                  f"## Running hypotheses\n{outcome['hypotheses']}\n",
                                                  encoding="utf-8")
        (outbox / "data" / "final_knowledge.md").write_text(knowledge.strip() + "\n", encoding="utf-8")
        usage = policy.usage
    except Exception as e:  # noqa: BLE001
        status = "failed"
        notes = f"{type(e).__name__}: {e}"
        deviations = "the run failed; see deviations.md"
        print(f"dw_agent: {notes}", file=sys.stderr)
    (outbox / "deviations.md").write_text(("none\n" if deviations == "none" else f"{notes}\n"), encoding="utf-8")
    files = sorted(p.relative_to(outbox).as_posix() for p in (outbox / "data").rglob("*") if p.is_file())
    (outbox / "RUN-RESULT.json").write_text(json.dumps({
        "run_id": run_id, "status": status, "started": started, "finished": stamp(), "files": files,
        "deviations": deviations, "notes": notes, "model_usage": usage,
        "scenario": a.scenario, "difficulty": a.difficulty, "seed": a.seed}, indent=1), encoding="utf-8")
    with open(root / "NOTES-RESUME.md", "a", encoding="utf-8") as f:
        f.write(f"- {stamp()} {job_id}: {status}; {notes[:160]}\n")
    (root / "ROUND-DONE.json").write_text(json.dumps({"status": "done" if status == "done" else "blocked",
                                                      "summary": notes[:1000],
                                                      "deliverables": [f"outbox/{run_id}/"]}, indent=1))
    print(f"dw_agent: {status}: {notes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
