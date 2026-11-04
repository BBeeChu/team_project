"""Shared machinery of the benchmark adapters: task specs, project scaffolding (config.toml, prompts/, domain/ rendered
from the benchmark's templates), run-folder lookup and the evaluation record."""
from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..util import atomic_write_text, iso_now, read_json, write_json

PKG_ROOT = Path(__file__).resolve().parents[1]           # .../auctopus/auctopus
REPO_ROOT = PKG_ROOT.parent                              # .../team_project/auctopus
TEAM_ROOT = REPO_ROOT.parent                             # .../team_project
RESOURCES = PKG_ROOT / "resources" / "benchmarks"
TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


@dataclass
class TaskSpec:
    id: str
    title: str
    description: str
    extra: dict = field(default_factory=dict)


@dataclass
class Paths:
    data_root: Path = TEAM_ROOT / "data"
    out_root: Path = TEAM_ROOT / "runs"

    def task_dir(self, bench: str, task: str) -> Path:
        return self.out_root / bench / task

    def project(self, bench: str, task: str) -> Path:
        return self.task_dir(bench, task) / "project"

    def eval_dir(self, bench: str, task: str) -> Path:
        return self.task_dir(bench, task) / "eval"


def render(text: str, variables: dict[str, str], where: str) -> str:
    """Replace {{TOKEN}} placeholders (the Auctopus {PLACEHOLDER}s are left to the engine)."""
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in variables:
            raise KeyError(f"{where}: no value for {{{{{key}}}}}")
        return variables[key]
    out = TOKEN_RE.sub(sub, text)
    if "[insert" in out:
        raise ValueError(f"{where}: an [insert: ...] part is still in the template")
    return out


def toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def toml_list(items: Iterable[str]) -> str:
    return "[" + ", ".join(toml_str(i) for i in items) + "]"


class Benchmark:
    """One benchmark adapter. Subclasses describe tasks, render the project and run the benchmark's evaluator."""

    name = ""                 # short id: mlr, rcb, dw
    label = ""                # printed name
    data_subdir = ""          # folder under team_project/data
    manuscript = "markdown"   # chain.manuscript
    theory_steps = ["02-proofs", "02b-positioning", "03-write", "04-exp"]
    file_steps = ["02b-positioning", "03-write", "03b-redeliver"]
    chain_flags = dict(verify=True, lab=False, figures=False, manager_redesign=False)
    reviewers = ["reviewer_a", "reviewer_b"]
    pull_exclude = [".git", "__pycache__", "*.ckpt", "*.pt", "*.pth", "*.npz", "*.npy", "*.h5", "*.hdf5", "*.parquet"]
    job_timeout_h = 3.0
    coder_max_turns = 80
    coder_budget_s = 5400

    # ------------------------------------------------------------------ tasks
    def data_dir(self, paths: Paths) -> Path:
        return paths.data_root / self.data_subdir

    def tasks(self, paths: Paths) -> list[TaskSpec]:
        raise NotImplementedError

    def task(self, paths: Paths, task_id: str) -> TaskSpec:
        for t in self.tasks(paths):
            if t.id == task_id:
                return t
        raise KeyError(f"{self.label}: unknown task {task_id!r} (see `python -m auctopus.bench list --bench "
                       f"{self.name}`)")

    # ---------------------------------------------------------------- project
    def variables(self, task: TaskSpec, paths: Paths, project: Path) -> dict[str, str]:
        """Values for the {{TOKEN}}s of this benchmark's prompt and domain templates."""
        return {"TASK_ID": task.id, "TASK_TITLE": task.title, "TASK_DESCRIPTION": task.description}

    def hpc_inputs(self, task: TaskSpec, paths: Paths) -> list[str]:
        """'local:remote' pairs pushed into the computational researcher's working folder."""
        return []

    def lab_toml(self, task: TaskSpec, paths: Paths, project: Path, model: str, mock: bool,
                 options: dict[str, str]) -> str:
        """The [lab] table for benchmarks whose instrument is an environment; '' when the lab stage is off."""
        return ""

    def extra_instructions(self, task: TaskSpec, paths: Paths) -> str:
        return ""

    def prepare(self, task: TaskSpec, paths: Paths, model: str, judge: str, mock: bool, effort: str = "medium",
                force: bool = False, options: dict[str, str] | None = None) -> Path:
        """Write the project folder and return the path of its config.toml."""
        project = paths.project(self.name, task.id)
        options = dict(options or {})
        if (project / "config.toml").exists() and not force:
            return project / "config.toml"
        project.mkdir(parents=True, exist_ok=True)
        variables = self.variables(task, paths, project)
        src = RESOURCES / self.name
        for sub in ("prompts", "domain"):
            dest = project / sub
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            for f in sorted((src / sub).glob("*.md")):
                atomic_write_text(dest / f.name, render(f.read_text(encoding="utf-8"), variables,
                                                         f"{self.name}/{sub}/{f.name}"))
        atomic_write_text(project / "config.toml",
                          self.config_toml(task, paths, project, model, judge, mock, effort, options))
        write_json(project / "task.json", {"benchmark": self.name, "task": task.id, "title": task.title,
                                           "model": model, "judge": judge, "mock": mock, "prepared": iso_now(),
                                           "options": options, "extra": task.extra})
        ignore = project / ".gitignore"
        if not ignore.exists():
            ignore.write_text("runs/\nremote-hpc/\nremote-lab/\n", encoding="utf-8")
        return project / "config.toml"

    def config_toml(self, task: TaskSpec, paths: Paths, project: Path, model: str, judge: str, mock: bool,
                    effort: str, options: dict[str, str]) -> str:
        provider = "mock" if mock else "openai"
        roles = ["proposer", "dedup", "pi", "pi_review", "feasibility", "manager", "safety"] + list(self.reviewers)
        role_tables = "\n".join(
            f"[roles.{r}]\nprovider = {toml_str(provider)}\nmodel = {toml_str(model)}\n"
            f"effort = {toml_str(effort)}\nmax_output_tokens = 0\nbackground = false\nweb_search = false\n"
            f"timeout_s = 1800\nmax_attempts = 3\nbackoff_s = [20, 60, 120]\n" for r in roles)
        ch = self.chain_flags
        python = toml_str(sys.executable)
        coder_model = "mock" if mock else model
        inputs = self.hpc_inputs(task, paths)
        lab = self.lab_toml(task, paths, project, model, mock, options)
        text = f"""# Auctopus project for {self.label}, task {task.id}. Written by auctopus.bench; edit and re-run freely.
[project]
name = {toml_str(f"{self.name}-{task.id}")}
runs_dir = "runs"
prompts_dir = "prompts"
domain_dir = "domain"
log_level = "INFO"
max_history_chars = 300000

[keys]
openai_api_key = "insert OpenAI API key here"      # OPENAI_API_KEY in the environment wins
anthropic_api_key = "insert Anthropic API key here"

{role_tables}
[proposals]
proposers = 5
concurrency = 3
stagger_s = 0.5
assess_after = 0
refusal_min_words = 250
dedup = true
max_batches = 4
revision = true
revision_proposers = 3
selection = "strict"
relax_after = 3
manager_exclusions_after = 2

[chain]
theory_steps = {toml_list(self.theory_steps)}
file_steps = {toml_list(self.file_steps)}
verify = {str(ch.get("verify", True)).lower()}
manuscript = {toml_str(self.manuscript)}
review_mode = "once"
lab = {str(ch.get("lab", False)).lower()}
manager_redesign = {str(ch.get("manager_redesign", False)).lower()}
lab_reruns = 1
figures = false
reviewers = {toml_list(self.reviewers)}
review_max_files = 9
review_max_mb = 18.0

[hpc]
transport = "local"
local_root = {toml_str(str(project / "remote-hpc"))}
remote_root = "work"
env_file = ""
agent = "api"
agent_model = {toml_str(coder_model)}
agent_command = {toml_str(f'{python} -m auctopus.bench.coder {{model_flag}}--prompt "{{prompt_file}}" --max-turns {self.coder_max_turns} --budget-s {self.coder_budget_s} --effort {effort}')}
job_timeout_h = {self.job_timeout_h}
poll_s = 5.0
detach = true
max_pull_mb = 300.0
pull_exclude = {toml_list(self.pull_exclude)}
inputs = {toml_list(inputs)}
extra_instructions = {toml_str(self.extra_instructions(task, paths))}

{lab}
[mock]
scenario = "win-first"

[bench]
name = {toml_str(self.name)}
task = {toml_str(task.id)}
data_dir = {toml_str(str(self.data_dir(paths)))}
judge_model = {toml_str(judge)}
agent_name = {toml_str(f"auctopus-{model}")}
mock = {str(mock).lower()}
"""
        return text

    # ------------------------------------------------------------------- runs
    @staticmethod
    def latest_run(project: Path) -> Path | None:
        base = project / "runs"
        runs = sorted(p for p in base.glob("2*") if (p / "state.json").exists()) if base.exists() else []
        return runs[-1] if runs else None

    @staticmethod
    def workdir(project: Path, run_dir: Path) -> Path | None:
        """The computational researcher's working folder (local transport)."""
        state = read_json(run_dir / "state.json", default={}) or {}
        rel = (state.get("hpc") or {}).get("dir")
        if not rel:
            return None
        p = project / "remote-hpc" / rel
        return p if p.is_dir() else None

    @staticmethod
    def selected_proposal(run_dir: Path) -> tuple[str, str]:
        """(selected proposal text, PI verdict) from the selecting batch."""
        sel = read_json(run_dir / "selection.json", default={}) or {}
        batch = sel.get("batch")
        verdict = (run_dir / "pi-verdict.md").read_text(encoding="utf-8") if (run_dir / "pi-verdict.md").exists() \
            else ""
        proposal = ""
        if batch and sel.get("proposal"):
            p = run_dir / "batches" / batch / f"{sel['proposal']}.md"
            if p.exists():
                proposal = p.read_text(encoding="utf-8")
        if not proposal and batch:
            files = sorted((run_dir / "batches" / batch).glob("proposer-*.md"))
            if files:
                proposal = files[0].read_text(encoding="utf-8")
        return proposal, verdict

    @staticmethod
    def run_stats(run_dir: Path) -> dict:
        """Cost-side facts of a run from its saved conversations: model calls, tokens, elapsed seconds."""
        calls, tokens_in, tokens_out, elapsed = 0, 0, 0, 0.0
        for f in run_dir.rglob("conversations/*.json"):
            data = read_json(f, default={}) or {}
            for t in data.get("turns", []):
                if t.get("role") != "assistant" or t.get("stage") == "compacted":
                    continue
                calls += 1
                u = t.get("usage") or {}
                tokens_in += int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
                tokens_out += int(u.get("output_tokens") or u.get("completion_tokens") or 0)
                elapsed += float(t.get("elapsed_s") or 0)
        state = read_json(run_dir / "state.json", default={}) or {}
        stages = {k: v.get("status") for k, v in (state.get("stages") or {}).items()}
        return {"model_calls": calls, "input_tokens": tokens_in, "output_tokens": tokens_out,
                "model_seconds": round(elapsed, 1), "stages": stages,
                "done": (run_dir / "RUN-DONE.json").exists(), "blocked": (run_dir / "RUN-BLOCKED.md").exists()}

    # ------------------------------------------------------------- evaluation
    def evaluate(self, task: TaskSpec, paths: Paths, project: Path, run_dir: Path, judge: str, dry: bool) -> dict:
        raise NotImplementedError

    def record(self, task: TaskSpec, paths: Paths, run_dir: Path, result: dict) -> Path:
        out = paths.eval_dir(self.name, task.id)
        out.mkdir(parents=True, exist_ok=True)
        result = {"benchmark": self.name, "task": task.id, "run": run_dir.name, "evaluated": iso_now(),
                  **result, "run_stats": self.run_stats(run_dir)}
        write_json(out / "evaluation.json", result)
        return out / "evaluation.json"


BENCHMARKS: dict[str, type[Benchmark]] = {}


def get_benchmark(name: str) -> Benchmark:
    if not BENCHMARKS:
        from . import dw, mlr, rcb  # noqa: F401 - registers the adapters
    if name not in BENCHMARKS:
        raise KeyError(f"unknown benchmark {name!r}; available: {', '.join(sorted(BENCHMARKS))}")
    return BENCHMARKS[name]()
