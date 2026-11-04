"""The orchestrator: stages in a fixed order, resumable at any point. The orchestrator carries every document between
the agents; the PI is one persistent conversation and every other model call starts fresh."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import Config
from .context import Ctx
from .conversation import Conversation
from .state import Blocked, Journal, RunState, write_blocked
from .util import LOG, now_stamp, read_json, setup_logging, write_json

# What each stage does, in the order they run (shown by `auctopus status`).
STAGE_NOTES = {
    "proposals": "proposers, dedup, the PI's verdict, revision batches, the manager's exclusions",
    "theory": "the PI: proofs, positioning, the manuscript, the computational test design",
    "verify": "the computational researcher runs the PI's computational test",
    "verify-review": "the PI reviews the verification; one revision",
    "lab": "feasibility, design, twin and packet, safety agent, instrument run, analysis",
    "figures": "figure plan, figure 1 build and review, the other figures reviewed as a set",
    "reviewers": "independent reviewers, the PI's triage, revision, final review",
    "deliver": "the final paper and its evidence, with checksums",
}


def stage_table(cfg: Config) -> list[tuple[str, Callable[[Ctx], object]]]:
    from .stages.deliver import Deliver
    from .stages.experiments import ReviewLoop, Verify
    from .stages.figures import Figures
    from .stages.front import Proposals, Theory
    from .stages.lab import LabStage
    from .stages.reviewers import Reviewers

    ch = cfg.chain
    table: list[tuple[str, Callable[[Ctx], object]]] = [
        ("proposals", Proposals),
        ("theory", Theory),
    ]
    if ch.verify:                        # BENCH: the computational test can be switched off (chain.verify = false)
        table += [("verify", Verify), ("verify-review", lambda c: ReviewLoop(c, "verify-review"))]
    if ch.lab:
        table.append(("lab", LabStage))
    if ch.figures:
        table.append(("figures", Figures))
    if ch.reviewers:
        table.append(("reviewers", Reviewers))
    table.append(("deliver", Deliver))
    return table


def new_run_dir(cfg: Config, label: str = "") -> Path:
    base = cfg.path(cfg.project.runs_dir)
    run = base / (now_stamp() + (f"-{label}" if label else ""))
    run.mkdir(parents=True, exist_ok=False)
    return run


def latest_run(cfg: Config) -> Path | None:
    base = cfg.path(cfg.project.runs_dir)
    runs = sorted(p for p in base.glob("2*") if (p / "state.json").exists()) if base.exists() else []
    return runs[-1] if runs else None


class Pipeline:
    def __init__(self, cfg: Config, run_dir: Path, dry_run: bool = False):
        self.cfg = cfg
        self.run_dir = Path(run_dir)
        setup_logging(cfg.project.log_level, self.run_dir / "pipeline.log")
        self.state = RunState(self.run_dir)
        self.journal = Journal(self.run_dir / "decisions-journal.md")
        self.ctx = Ctx(cfg=cfg, run_dir=self.run_dir, state=self.state, journal=self.journal, dry_run=dry_run)
        self.table = stage_table(cfg)
        self.names = [n for n, _ in self.table]

    # ------------------------------------------------------------------- reset
    def reset_from(self, stage: str) -> None:
        """Forget `stage` and every later stage: their state, their PI turns and their one-shot conversations."""
        if stage not in self.names:
            raise ValueError(f"unknown stage {stage!r}; stages: {', '.join(self.names)}")
        doomed = set(self.names[self.names.index(stage):])
        stages = self.state.data["stages"]
        for key in list(stages):
            if key in doomed or stages[key].get("owner") in doomed:
                stages.pop(key)
        self.state.save()
        conv_dir = self.run_dir / "conversations"
        for f in conv_dir.glob("*.json") if conv_dir.exists() else []:
            data = read_json(f, default={}) or {}
            if f.name == "pi.json":
                turns = data.get("turns", [])
                cut = next((i for i, t in enumerate(turns) if t.get("owner") in doomed), None)
                if cut is not None:
                    data["turns"] = turns[:cut]
                    data["pending"] = None
                    write_json(f, data)
            elif data.get("owner") in doomed:
                f.unlink()
        self.journal.say(f"reset: stages from '{stage}' on will run again")

    # --------------------------------------------------------------------- run
    def run(self, from_stage: str | None = None, until: str | None = None, skip: list[str] | None = None) -> int:
        stopped = self.run_dir / "RUN-STOPPED.md"
        if stopped.exists():
            LOG.error("this run is stopped (%s); delete that file to continue", stopped)
            return 1
        (self.run_dir / "RUN-BLOCKED.md").unlink(missing_ok=True)
        for s in skip or []:
            if s not in self.names:
                raise ValueError(f"unknown stage to skip: {s!r}")
            if not self.state.is_done(s):
                self.state.mark(s, "done", skipped=True)
        if from_stage:
            self.reset_from(from_stage)
        if until and until not in self.names:
            raise ValueError(f"unknown stage {until!r}")
        self.journal.say(f"run {self.run_dir.name}: starting (stages: {', '.join(self.names)})")
        resume = f"auctopus resume {self.run_dir}"
        for name, factory in self.table:
            if self.state.is_done(name):
                if name == until:
                    break
                continue
            self.state.owner = name
            Conversation.owner = name
            self.state.mark(name, "running")
            try:
                factory(self.ctx).run()
            except Blocked as e:
                from .stages.lab import AwaitingApproval
                self.state.mark(name, "blocked", reason=str(e)[:4000])
                write_blocked(self.run_dir, name, str(e), resume)
                self.journal.say(f"STOPPED at {name}: {e}")
                return 2 if isinstance(e, AwaitingApproval) else 1
            except KeyboardInterrupt:
                self.state.mark(name, "pending", reason="interrupted")
                self.journal.say(f"interrupted during {name}; resume with: {resume}")
                raise
            except Exception as e:  # noqa: BLE001 - recorded, then re-raised for the traceback
                self.state.mark(name, "blocked", reason=f"{type(e).__name__}: {e}"[:4000])
                write_blocked(self.run_dir, name, f"{type(e).__name__}: {e}", resume)
                self.journal.say(f"FAILED at {name}: {type(e).__name__}: {e}")
                raise
            finally:
                Conversation.owner = None
            self.state.mark(name, "done")
            self.journal.say(f"stage {name}: done")
            if name == until:
                self.journal.say(f"stopping after '{until}' as requested")
                return 0
        if all(self.state.is_done(n) for n in self.names):
            self.journal.say(f"run {self.run_dir.name}: complete")
        return 0

    def status_rows(self) -> list[tuple[str, str, str]]:
        rows = []
        for n in self.names:
            st = self.state.data["stages"].get(n, {"status": "pending"})
            note = st.get("reason", "")
            if n == "proposals" and st.get("batches"):
                note = f"{len(st['batches'])} batch(es); selected: {st.get('selected') or '-'}"
            if n == "lab" and st.get("decision"):
                note = note or (f"decision {st['decision']}" + (f", safety {st['safety_verdict']}"
                                                              if st.get("safety_verdict") else ""))
            if st.get("skipped"):
                note = "skipped"
            rows.append((n, st.get("status", "pending"), note[:100]))
        return rows
