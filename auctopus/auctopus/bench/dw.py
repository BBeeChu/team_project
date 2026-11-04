"""DiscoveryWorld adapter (team_project/data/discoveryworld).

DiscoveryWorld is an interactive environment: an agent explores a 2D world, measures, and must discover a hidden
rule (which nutrient grows plants, which rock is oldest, ...). Auctopus's laboratory stage fits it as the instrument:

    proposals   proposers write hypotheses and a plan for the task's scientific question (the task description and
                an initial observation form the sample card); strict PI selection
    theory      02-proofs (hypotheses, precommitted predictions, decision rule), 03-write (lab notebook main.md),
                04-exp (protocol draft); verify is off (there is no computation to run before the experiment)
    lab         feasibility review against instrument.md (the environment's capabilities), PI GO/NO-GO, manager
                redesign after a NO-GO, run packet built by the API coding agent (protocol, results schema,
                analysis script, twin report), PI packet review, then the experimentalist (dw_agent) executes the
                protocol inside the environment and returns the trajectory, notes and final knowledge; the PI may
                order one rerun; the coding agent analyses the returned data and writes knowledge.md; PI review
    reviewers   two referees, triage, revision, final review; deliver

Evaluation uses the benchmark's own measures: task completion and the procedural scorecard from the environment
(getTaskScorecard) and the explanatory-knowledge score from scripts/knowledgeScorer.py (LLM judge over the task's
critical questions), applied to the harness's final knowledge.md and to the experimentalist's own notes.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

from ..util import read_json, write_json
from .base import BENCHMARKS, Benchmark, Paths, TaskSpec, toml_str

THEMES = ["Combinatorial Chemistry", "Archaeology Dating", "Plant Nutrients", "Reactor Lab", "Lost in Translation",
          "Space Sick", "Proteomics", "It's (not) Rocket Science!"]
DIFFICULTIES = ["Easy", "Normal", "Challenge"]
SEEDS = [0, 1, 2, 3, 4]
DEFAULT_STEPS = {"Easy": 100, "Normal": 1000, "Challenge": 1000}


def slug(theme: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", theme.lower()).strip("-")


class DiscoveryWorld(Benchmark):
    name = "dw"
    label = "DiscoveryWorld"
    data_subdir = "discoveryworld"
    theory_steps = ["02-proofs", "03-write", "04-exp"]
    file_steps = ["03-write", "03b-redeliver"]
    chain_flags = dict(verify=False, lab=True, figures=False, manager_redesign=True)
    coder_max_turns = 40
    coder_budget_s = 2400

    def tasks(self, paths: Paths) -> list[TaskSpec]:
        out = []
        for theme in THEMES:
            for diff in DIFFICULTIES:
                for seed in SEEDS:
                    tid = f"{slug(theme)}-{diff.lower()}-s{seed}"
                    out.append(TaskSpec(tid, f"{theme} / {diff} / seed {seed}", "(loaded from the environment at "
                                        "prepare time)", {"scenario": theme, "difficulty": diff, "seed": seed}))
        return out

    # -------------------------------------------------------------- environment
    def env_root(self, paths: Paths) -> Path:
        return self.data_dir(paths)

    def load_env(self, paths: Paths, scenario: str, difficulty: str, seed: int):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        root = str(self.env_root(paths))
        if root not in sys.path:
            sys.path.insert(0, root)
        cwd = os.getcwd()
        os.chdir(root)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                from discoveryworld.DiscoveryWorldAPI import DiscoveryWorldAPI
                api = DiscoveryWorldAPI(threadID=4242)
                if not api.loadScenario(scenarioName=scenario, difficultyStr=difficulty, randomSeed=seed,
                                        numUserAgents=1):
                    raise RuntimeError(f"could not load {scenario} / {difficulty} / seed {seed}")
                obs = api.getAgentObservation(agentIdx=0)
                card = api.getTaskScorecard()
                actions = api.listKnownActions(limited=False)
                teleports = list(api.listTeleportLocationsDict().keys())
        finally:
            os.chdir(cwd)
        return obs, card, actions, teleports

    def describe(self, paths: Paths, task: TaskSpec) -> dict:
        """Task description and an initial observation (no oracle fields) for the sample card and instrument."""
        cache = paths.task_dir(self.name, task.id) / "task_env.json"
        if cache.exists():
            return read_json(cache)
        from .dw_agent import summarize_observation
        obs, card, actions, teleports = self.load_env(paths, task.extra["scenario"], task.extra["difficulty"],
                                                      task.extra["seed"])
        summary = summarize_observation(obs, type("A", (), {"listTeleportLocationsDict": lambda s: {t: 0 for t in
                                                                                                    teleports}})())
        info = {"task_description": card[0]["taskDescription"] if card else "",
                "task_name": card[0]["taskName"] if card else "",
                "initial_observation": summary, "actions": actions, "teleport_locations": teleports}
        cache.parent.mkdir(parents=True, exist_ok=True)
        write_json(cache, info)
        return info

    def variables(self, task: TaskSpec, paths: Paths, project: Path) -> dict[str, str]:
        info = self.describe(paths, task)
        task.description = info["task_description"]
        v = super().variables(task, paths, project)
        steps = int(task.extra.get("steps") or DEFAULT_STEPS[task.extra["difficulty"]])
        obs = dict(info["initial_observation"])
        obs.pop("discovery_feed", None)
        v.update({
            "SCENARIO": task.extra["scenario"], "DIFFICULTY": task.extra["difficulty"],
            "SEED": str(task.extra["seed"]), "STEPS": str(steps),
            "TASK_CARD": " ".join(info["task_description"].split()),
            "INITIAL_OBSERVATION": json.dumps(obs, ensure_ascii=False, indent=1)[:6000],
            "ACTIONS": json.dumps(info["actions"], indent=1),
            "TELEPORTS": ", ".join(info["teleport_locations"]) or "(none)",
        })
        return v

    def lab_toml(self, task: TaskSpec, paths: Paths, project: Path, model: str, mock: bool,
                 options: dict[str, str]) -> str:
        steps = int(options.get("steps") or DEFAULT_STEPS[task.extra["difficulty"]])
        task.extra["steps"] = steps
        agent_model = "mock" if mock else model
        cmd = (f'"{sys.executable}" -m auctopus.bench.dw_agent --prompt "{{prompt_file}}" --model {agent_model} '
               f'--effort low --scenario "{task.extra["scenario"]}" --difficulty {task.extra["difficulty"]} '
               f'--seed {task.extra["seed"]} --steps {steps} --dw-root "{self.env_root(paths)}"')
        return f"""[lab]
transport = "local"
local_root = {toml_str(str(project / "remote-lab"))}
remote_root = "work"
env_file = ""
agent = "custom"
agent_model = {toml_str(agent_model)}
agent_command = {toml_str(cmd)}
job_timeout_h = 6.0
poll_s = 10.0
detach = true
max_pull_mb = 500.0
safety_review = false
require_approval = false
extra_instructions = ""
"""

    def extra_instructions(self, task: TaskSpec, paths: Paths) -> str:
        return ("There is no instrument API in this folder: the experimentalist runs the protocol inside the "
                "DiscoveryWorld environment and returns data/trajectory.jsonl (one JSON object per step with the "
                "observation summary, the action, its success and the environment's message), data/notes.md and "
                "data/final_knowledge.md. The analysis code in lab_packet/analysis/ must read that trajectory "
                "format. The twin is a written walk-through of the protocol against the environment's rules, not "
                "a simulation.")

    # ------------------------------------------------------------- evaluation
    def evaluate(self, task: TaskSpec, paths: Paths, project: Path, run_dir: Path, judge: str, dry: bool) -> dict:
        state = read_json(run_dir / "state.json", default={}) or {}
        lab = (state.get("stages") or {}).get("lab") or {}
        runs = lab.get("lab_runs") or []
        result = {"judge": judge, "scores": {}, "details": {}, "missing": []}
        final = lab.get("result_final") or (runs[-1] if runs else None)
        if not final:
            result["missing"].append("no acquisition in the lab stage (decision: %s)" % lab.get("decision"))
        oracle = None
        if final:
            scores_file = project / "remote-lab" / "work" / "scores" / f"{final['run_id']}.json"
            oracle = read_json(scores_file, default=None)
            if oracle is None:
                result["missing"].append(f"oracle scorecard {scores_file.name}")
        card = (oracle or {}).get("scorecard") or []
        if card:
            c = card[0]
            result["scores"].update({"completed_successfully": int(bool(c.get("completedSuccessfully"))),
                                     "completed": int(bool(c.get("completed"))),
                                     "procedure_score": c.get("scoreNormalized"),
                                     "steps_taken": oracle.get("steps_taken"), "step_budget": oracle.get("step_budget")})
            result["details"]["scorecard"] = c.get("scoreCard")
        work = self.workdir(project, run_dir)
        knowledge = {}
        if work and (work / "knowledge.md").exists():
            knowledge["harness"] = (work / "knowledge.md").read_text(encoding="utf-8", errors="replace")
        else:
            result["missing"].append("knowledge.md from the analysis round")
        if final:
            fk = run_dir / "lab_results" / final["run_id"] / "data" / "final_knowledge.md"
            if fk.exists():
                knowledge["experimentalist"] = fk.read_text(encoding="utf-8", errors="replace")
        result["details"]["knowledge"] = knowledge
        result["lab_decision"] = lab.get("decision")
        result["acquisitions"] = len(runs)
        if dry or not knowledge:
            result["note"] = "dry evaluation: environment scores read, the knowledge judge was not called"
            return result
        root = self.env_root(paths)
        for p in (str(root), str(root / "scripts")):
            if p not in sys.path:
                sys.path.insert(0, p)
        from .judges import dw_knowledge_scorer
        cwd = os.getcwd()
        os.chdir(root)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                scorer = dw_knowledge_scorer(judge)
            for who, text in knowledge.items():
                with contextlib.redirect_stdout(io.StringIO()):
                    ev = scorer.evaluateKnowledge(task.extra["scenario"], task.extra["difficulty"],
                                                  task.extra["seed"], text)
                result["details"][f"knowledge_eval_{who}"] = ev
                if ev:
                    result["scores"][f"knowledge_score_{who}"] = ev[0].get("evaluation_totalscore")
        finally:
            os.chdir(cwd)
        write_json(paths.eval_dir(self.name, task.id) / "dw_details.json", result["details"])
        return result


BENCHMARKS["dw"] = DiscoveryWorld
