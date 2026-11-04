"""An API coding agent: the computational researcher as a tool-using model loop (OpenAI Responses API), so Auctopus
can run without Codex or Claude Code installed. Configure it with `agent = "api"` (see remote/agents.py).

    python -m auctopus.bench.coder --model gpt-5-nano --prompt .auctopus/prompts/<job>.md [--max-turns 80]
                                   [--budget-s 5400] [--effort medium]

It runs in the agent's working folder, exactly where Codex would run: it reads the task prompt, works with four tools
(bash, write_file, read_file, list_files), keeps NOTES-RESUME.md, and finishes with ROUND-DONE.json. Every tool call
and output is saved to .auctopus/coder/<job>.json (the experiment log that MLR-Bench's experiment reviewer reads).

`--model mock` writes benchmark-shaped stand-in files offline (the dry-run counterpart of remote/mock_agent.py).

Safety: like `codex exec --dangerously-bypass-approvals-and-sandbox`, the shell tool runs whatever the model asks in
the working folder's environment. Use a dedicated account or container for real runs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SYSTEM = """You are the computational researcher of an autonomous research laboratory. You work alone in the current
folder with four tools: bash (run a shell command here), write_file, read_file and list_files. Nobody answers
questions: when something is ambiguous, choose the most defensible option, note it, and continue.

Working rules
- Read the task first (the user message), then NOTES-RESUME.md and existing reports if present.
- Run real computations. Never fabricate numbers, plots or logs: every number you report must come from a command
  you ran in this folder, and the code that produced it must be saved here.
- Keep experiments small enough to finish inside the time budget; prefer subsets and short training over timeouts.
- Save figures as PNG files and reference them by relative path. Write Markdown, never LaTeX, unless the task says
  otherwise.
- Keep NOTES-RESUME.md current (what was done, where results are, what remains).
- Finish by writing ROUND-DONE.json: {"status": "done" or "blocked", "summary": "<one paragraph of plain facts>",
  "deliverables": ["<paths>"]}. Then reply with a short summary and stop calling tools.
"""

TOOLS = [
    {"type": "function", "name": "bash",
     "description": "Run a shell command in the working folder (bash). Returns exit code, stdout and stderr, "
                    "truncated to the last part when long. Use it to run Python, install packages with pip, "
                    "inspect data, and so on.",
     "parameters": {"type": "object",
                    "properties": {"command": {"type": "string"},
                                   "timeout_s": {"type": "integer",
                                                 "description": "seconds before the command is killed "
                                                                "(default 600, maximum 3600)"}},
                    "required": ["command"]}},
    {"type": "function", "name": "write_file",
     "description": "Create or overwrite a text file (path relative to the working folder) with the given content.",
     "parameters": {"type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}},
    {"type": "function", "name": "read_file",
     "description": "Read a text file (path relative to the working folder); long files are cut in the middle.",
     "parameters": {"type": "object",
                    "properties": {"path": {"type": "string"},
                                   "max_chars": {"type": "integer", "description": "default 20000"}},
                    "required": ["path"]}},
    {"type": "function", "name": "list_files",
     "description": "List files under a folder (relative path, default '.'), with sizes, up to 300 entries.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}},
]

MAX_OUTPUT = 12000


def stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    head = limit // 3
    return text[:head] + f"\n... [{len(text) - head - (limit - head)} characters omitted] ...\n" + text[-(limit - head):]


def safe_path(here: Path, rel: str) -> Path:
    p = (here / rel).resolve()
    if p != here and here not in p.parents:
        raise ValueError(f"path escapes the working folder: {rel}")
    return p


# ------------------------------------------------------------------------------------------------------- tools

def tool_bash(here: Path, command: str, timeout_s: int | None = None) -> str:
    timeout = max(5, min(int(timeout_s or 600), 3600))
    env = dict(os.environ)
    env.setdefault("MPLBACKEND", "Agg")
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    try:
        proc = subprocess.run(command, shell=True, cwd=here, capture_output=True, text=True, timeout=timeout,
                              env=env, stdin=subprocess.DEVNULL, errors="replace")
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return f"[timeout after {timeout} s; the command was killed]\nSTDOUT (tail):\n{truncate(out, 4000)}"
    return (f"[exit code {proc.returncode}]\nSTDOUT:\n{truncate(proc.stdout, MAX_OUTPUT * 2 // 3)}\n"
            f"STDERR:\n{truncate(proc.stderr, MAX_OUTPUT // 3)}")


def tool_write(here: Path, path: str, content: str) -> str:
    p = safe_path(here, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {path} ({len(content)} characters)"


def tool_read(here: Path, path: str, max_chars: int | None = None) -> str:
    p = safe_path(here, path)
    if not p.is_file():
        return f"[no such file: {path}]"
    limit = max(500, min(int(max_chars or 20000), 200000))
    text = p.read_text(encoding="utf-8", errors="replace")
    return truncate(text, limit)


def tool_list(here: Path, path: str | None = None) -> str:
    base = safe_path(here, path or ".")
    if not base.is_dir():
        return f"[no such folder: {path}]"
    rows = []
    for p in sorted(base.rglob("*")):
        if ".auctopus" in p.parts or "__pycache__" in p.parts or ".git" in p.parts:
            continue
        if p.is_file():
            rows.append(f"{p.stat().st_size:>10}  {p.relative_to(here).as_posix()}")
        if len(rows) >= 300:
            rows.append("... (truncated at 300 entries)")
            break
    return "\n".join(rows) or "(empty)"


def run_tool(here: Path, name: str, args: dict) -> str:
    try:
        if name == "bash":
            return tool_bash(here, args.get("command", ""), args.get("timeout_s"))
        if name == "write_file":
            return tool_write(here, args["path"], args.get("content", ""))
        if name == "read_file":
            return tool_read(here, args["path"], args.get("max_chars"))
        if name == "list_files":
            return tool_list(here, args.get("path"))
        return f"[unknown tool {name}]"
    except Exception as e:  # noqa: BLE001 - reported to the model
        return f"[tool error: {type(e).__name__}: {e}]"


# -------------------------------------------------------------------------------------------------------- agent

class Transcript:
    """The experiment log: the task, every assistant message, every tool call with its output."""

    def __init__(self, path: Path):
        self.path = path
        self.items: list[dict] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def add(self, item: dict) -> None:
        item["at"] = stamp()
        self.items.append(item)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"usage": self.usage, "messages": self.items}, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.path)


def create_with_retries(client, **kwargs):
    delays = [10, 30, 60]
    for attempt in range(len(delays) + 1):
        try:
            return client.responses.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            names = {c.__name__ for c in type(e).__mro__}
            status = getattr(e, "status_code", None)
            transient = bool(names & {"RateLimitError", "APIConnectionError", "APITimeoutError",
                                      "InternalServerError"}) or (status is not None and status >= 500)
            if not transient or attempt == len(delays):
                raise
            print(f"coder: transient API error ({e}); retry in {delays[attempt]} s", flush=True)
            time.sleep(delays[attempt])


def agent_loop(here: Path, prompt: str, model: str, effort: str, max_turns: int, budget_s: float,
               transcript: Transcript) -> str:
    import openai
    client = openai.OpenAI(max_retries=2, timeout=600)
    transcript.add({"role": "user", "content": prompt})
    input_items: list[dict] = [{"role": "user", "content": prompt}]
    previous = None
    t0 = time.monotonic()
    last_text = ""
    warned = False
    for turn in range(1, max_turns + 1):
        over = time.monotonic() - t0 > budget_s
        if over and not warned:
            warned = True
            note = ("TIME BUDGET EXHAUSTED. Stop experimenting now: save what you have, update NOTES-RESUME.md, "
                    "write ROUND-DONE.json (status done if the deliverables exist, else blocked) and reply with a "
                    "summary without further tool calls.")
            input_items.append({"role": "user", "content": note})
            transcript.add({"role": "user", "content": note})
        kwargs = dict(model=model, instructions=SYSTEM, input=input_items, tools=TOOLS, store=True)
        if effort:
            kwargs["reasoning"] = {"effort": effort}
        if previous:
            kwargs["previous_response_id"] = previous
        resp = create_with_retries(client, **kwargs)
        previous = resp.id
        u = getattr(resp, "usage", None)
        if u is not None:
            transcript.usage["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
            transcript.usage["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
        transcript.usage["calls"] += 1
        text = (getattr(resp, "output_text", "") or "").strip()
        calls = [o for o in (resp.output or []) if getattr(o, "type", "") == "function_call"]
        if text:
            last_text = text
            transcript.add({"role": "assistant", "content": text})
            print(f"coder[{turn}]: {text[:300]}", flush=True)
        if not calls:
            break
        input_items = []
        for c in calls:
            try:
                args = json.loads(c.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            print(f"coder[{turn}]: {c.name} {json.dumps(args)[:200]}", flush=True)
            out = run_tool(here, c.name, args)
            transcript.add({"role": "tool", "name": c.name, "input": args, "output": out})
            input_items.append({"type": "function_call_output", "call_id": c.call_id, "output": out})
        if warned and turn >= max_turns - 1:
            break
    return last_text


# --------------------------------------------------------------------------------------------------------- mock

def task_key(job_id: str) -> str:
    return re.sub(r"-\d+-\d{8}T\d{6}(-r\d+)?$", "", job_id)


def mock_run(here: Path, job_id: str) -> str:
    """Benchmark-shaped stand-in deliverables (no model): a Markdown manuscript, results, code, a report with a
    figure, a lab packet or a lab analysis, depending on the task."""
    from ..remote.mock_agent import tiny_png
    key = task_key(job_id)
    made: list[str] = []
    main = here / "main.md"
    if not main.exists():
        main.write_text("# Mock manuscript\n\n## Precommitted predictions\nThe effect is positive.\n",
                        encoding="utf-8")
    if key == "lab-packet":
        lp = here / "lab_packet"
        (lp / "analysis").mkdir(parents=True, exist_ok=True)
        (lp / "twin").mkdir(parents=True, exist_ok=True)
        (lp / "README.md").write_text("# Run packet (mock)\n\nprotocol.md, results_schema.md, analysis/, twin/\n")
        (lp / "protocol.md").write_text("1. Pick up the instrument.\n2. Measure each sample.\n"
                                        "3. Decision rule: the sample with the predicted reading confirms H1.\n")
        (lp / "results_schema.md").write_text("- data/trajectory.jsonl: one JSON object per step\n"
                                              "- data/final_knowledge.md: the agent's final knowledge\n")
        (lp / "analysis" / "analyze.py").write_text("import json,sys\nprint('mock analysis')\n")
        (lp / "twin" / "report.md").write_text("Twin: the protocol fits in the step budget.\n")
        made.append("lab_packet/")
    elif key == "lab-analysis":
        rr = here / "lab_results" / "RUN-RESULT.json"
        status = json.loads(rr.read_text())["status"] if rr.exists() else "missing"
        verdict = "SUPPORTED" if status == "done" else "INCONCLUSIVE"
        (here / "LAB_ANALYSIS.md").write_text(f"# Laboratory analysis (mock)\n\nRun status: {status}\n"
                                              f"Verdict: {verdict}\n")
        (here / "knowledge.md").write_text("The mock analysis found that the predicted nutrient makes seeds "
                                           "grow.\n")
        main.write_text(main.read_text(encoding="utf-8") + f"\n## Experiment\nLaboratory test: {verdict}.\n",
                        encoding="utf-8")
        made += ["LAB_ANALYSIS.md", "knowledge.md"]
    else:
        n = len(list(here.glob("RESULTS-*.md"))) + 1
        (here / "results").mkdir(exist_ok=True)
        (here / "code").mkdir(exist_ok=True)
        (here / "report" / "images").mkdir(parents=True, exist_ok=True)
        (here / "outputs").mkdir(exist_ok=True)
        (here / "code" / "run_experiment.py").write_text("print('mock experiment: accuracy 0.5')\n")
        (here / "results" / "results.md").write_text(f"# Results (mock, task {n})\n\n| method | metric |\n|---|---|\n"
                                                     "| baseline | 0.50 |\n| proposed | 0.50 |\n")
        (here / "outputs" / "metrics.json").write_text(json.dumps({"baseline": 0.5, "proposed": 0.5}))
        (here / "report" / "images" / "fig1.png").write_bytes(tiny_png())
        (here / "report" / "report.md").write_text("# Report (mock)\n\n## Methodology\nMock.\n\n## Results\n"
                                                   "![fig](images/fig1.png)\n\n## Discussion\nMock.\n")
        (here / f"RESULTS-{n}.md").write_text(f"# Results of task {n}\n\nThe experiment ran end to end (mock).\n")
        main.write_text(main.read_text(encoding="utf-8") + f"\n## Result {n}\nThe prediction held (mock).\n",
                        encoding="utf-8")
        made += ["results/results.md", "report/report.md", f"RESULTS-{n}.md"]
    (here / "EXPERIMENT_REPORT.md").write_text(f"# Report\n\nUpdated {stamp()} (mock).\n")
    return "mock task completed: " + ", ".join(made)


# --------------------------------------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="API coding agent for Auctopus (computational researcher)")
    ap.add_argument("--prompt", required=True, help="the task prompt file (.auctopus/prompts/<job>.md)")
    ap.add_argument("--model", default="gpt-5-nano")
    ap.add_argument("--effort", default="medium", help="reasoning effort (low, medium, high) or '' to omit")
    ap.add_argument("--max-turns", type=int, default=80)
    ap.add_argument("--budget-s", type=float, default=5400)
    a = ap.parse_args()
    here = Path.cwd().resolve()
    prompt_file = Path(a.prompt)
    if not prompt_file.exists():
        print(f"coder: no prompt file {a.prompt}", file=sys.stderr)
        return 2
    job_id = prompt_file.stem
    prompt = prompt_file.read_text(encoding="utf-8")
    transcript = Transcript(here / ".auctopus" / "coder" / f"{job_id}.json")
    t0 = time.monotonic()
    status, summary = "done", ""
    try:
        if a.model == "mock":
            summary = mock_run(here, job_id)
            transcript.add({"role": "assistant", "content": summary})
        else:
            summary = agent_loop(here, prompt, a.model, a.effort, a.max_turns, a.budget_s, transcript)
    except Exception as e:  # noqa: BLE001 - the job must still leave a completion record
        status, summary = "blocked", f"coder stopped: {type(e).__name__}: {e}"
        transcript.add({"role": "system", "content": summary})
        print(summary, file=sys.stderr)
    done = here / "ROUND-DONE.json"
    if not done.exists() or status == "blocked":
        changed = sorted(p.relative_to(here).as_posix() for p in here.rglob("*")
                         if p.is_file() and ".auctopus" not in p.parts and p.stat().st_mtime >= time.time()
                         - (time.monotonic() - t0) - 1)[:50]
        done.write_text(json.dumps({"status": status, "summary": (summary or "no summary")[:2000],
                                    "deliverables": changed, "written_by": "auctopus.bench.coder"}, indent=1),
                        encoding="utf-8")
    with open(here / "NOTES-RESUME.md", "a", encoding="utf-8") as f:
        f.write(f"- {stamp()} task {job_id} ({a.model}): {status}; {(summary or '')[:200].replace(chr(10), ' ')}\n")
    print(f"coder: {status} ({transcript.usage['calls']} model calls, {transcript.usage['input_tokens']} in / "
          f"{transcript.usage['output_tokens']} out tokens, {time.monotonic() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
