"""Run state on disk (state.json) and the decisions journal.

Every stage records status pending/running/done/blocked plus its own sub-flags, so a stopped run resumes at the first
stage that is not done, and each stage resumes at its first unfinished step.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import LOG, atomic_write_text, iso_now, read_json, write_json


class Blocked(RuntimeError):
    """A stage cannot continue on its own (missing artefact, repeated failure, a gate that said no, or a wait for
    approval); the run stops with RUN-BLOCKED.md and can be resumed."""


class RunState:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / "state.json"
        self.data: dict[str, Any] = read_json(self.path, default=None) or {"created": iso_now(), "stages": {}}
        self.owner: str | None = None       # the pipeline stage currently running (tags sub-step records)

    def save(self) -> None:
        write_json(self.path, self.data)

    def stage(self, name: str) -> dict:
        """A stage's (or sub-step's) record. New sub-step records remember which stage created them, so restarting
        a run from an earlier stage also forgets the sub-steps it owns."""
        stages = self.data["stages"]
        if name not in stages:
            stages[name] = {"status": "pending", "owner": self.owner or name}
        return stages[name]

    def mark(self, name: str, status: str, **extra: Any) -> None:
        st = self.stage(name)
        st["status"] = status
        st[f"{status}_at"] = iso_now()
        st.update(extra)
        self.save()

    def is_done(self, name: str) -> bool:
        return self.data["stages"].get(name, {}).get("status") == "done"   # never creates a record

    def reset_from(self, names: list[str]) -> None:
        for n in names:
            self.data["stages"].pop(n, None)
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()


class Journal:
    """Append-only log of every decision the pipeline takes (decisions-journal.md in the run folder)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def say(self, msg: str) -> None:
        LOG.info(msg)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"- {iso_now()} {msg}\n")


def write_blocked(run_dir: Path, stage: str, reason: str, resume_cmd: str) -> None:
    atomic_write_text(run_dir / "RUN-BLOCKED.md",
                      f"# Run stopped at stage '{stage}'\n\n{reason}\n\nWhen fixed, resume with:\n\n"
                      f"    {resume_cmd}\n")
