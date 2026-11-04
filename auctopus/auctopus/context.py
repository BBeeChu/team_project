"""Everything a stage needs: configuration, run folder, state, journal, the PI conversation and the remotes."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from .attachments import build_content
from .config import Config
from .conversation import Conversation
from .prompt_builder import load_prompt
from .state import Journal, RunState


@dataclass
class Ctx:
    cfg: Config
    run_dir: Path
    state: RunState
    journal: Journal
    dry_run: bool = False
    stop: threading.Event = field(default_factory=threading.Event)
    _transports: dict = field(default_factory=dict)

    # ----------------------------------------------------------------- folders
    @property
    def package(self) -> Path:
        p = self.run_dir / "package"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def conv_dir(self) -> Path:
        p = self.run_dir / "conversations"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------------------------ models
    def pi(self) -> Conversation:
        """The PI's conversation: the selection, the theory steps, the reviews and the rulings all share it."""
        return Conversation(self.cfg, self.conv_dir / "pi.json", "pi")

    def prompt(self, name: str, **subs: str) -> str:
        return load_prompt(self.cfg, name, **subs)

    def content(self, prompt: str, files: list[Path] | None = None, note: str | None = None) -> str | list[dict]:
        return build_content(prompt, files, note=note, max_mb=self.cfg.chain.review_max_mb)

    # ----------------------------------------------------------------- remotes
    def transport(self, label: str):
        if label not in self._transports:
            from .remote.transport import make_transport
            rc = self.cfg.hpc if label == "hpc" else self.cfg.lab
            self._transports[label] = make_transport(rc, label)
        return self._transports[label]
