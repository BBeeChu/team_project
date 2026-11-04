"""Stages that drive the computational researcher: the first verification task and the PI's review loops."""
from __future__ import annotations

from ..state import Blocked
from .chain import Chain


class Verify(Chain):
    """Push the paper package and the PI's computational test design to the HPC and run the first task (05-codex)."""

    def run(self) -> None:
        exp = self.rd / "04-exp-reply.md"
        if not exp.exists():
            raise Blocked("verify: no computational test design (04-exp-reply.md)")
        remote = self.ensure_hpc_dir()           # BENCH: shared with the lab stage (see Chain.ensure_hpc_dir)
        if not self.ctx.transport("hpc").exists(f"{remote}/experiment.md"):
            raise Blocked(f"verify: experiment.md did not arrive in {remote}")
        self.codex_task("verify", self.ctx.prompt("05-codex.md"))


class ReviewLoop(Chain):
    def __init__(self, ctx, key: str):
        super().__init__(ctx)
        self.key = key

    def run(self) -> None:
        self.review_loop(self.key, self.cfg.chain.max_review_rounds)
