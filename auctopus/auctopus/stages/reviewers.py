"""Stage 'reviewers': independent reviewers read only the manuscript, in new conversations; the PI triages their
reports into a ruling table and an instruction list; the computational researcher applies it; one final review."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..conversation import one_shot
from ..llm import LLMError
from ..state import Blocked
from ..util import LOG
from .chain import Chain


class Reviewers(Chain):
    key = "reviewers"

    def run(self) -> None:
        st = self.ctx.state.stage(self.key)
        round_dir = self.latest_round()
        if round_dir is None:
            raise Blocked("reviewers: no manuscript yet")
        pdf, tex = self.main_pdf(round_dir), self.main_doc(round_dir, self.cfg.chain.manuscript)
        files = [f for f in (pdf, tex) if f]
        if not files:
            raise Blocked("reviewers: the latest round has neither a PDF nor a manuscript source")
        prompt = self.ctx.prompt("10-cold-referee.md")

        def review(role: str) -> Path | None:
            out = self.rd / f"{role.replace('_', '-')}-report.md"
            try:
                one_shot(self.cfg, role, self.ctx.content(prompt, files), stage=f"{role}-report", out_file=out,
                         record=self.ctx.conv_dir / f"{role}-report.json")
                return out
            except LLMError as e:
                LOG.warning("%s failed: %s", role, e)
                return None

        roles = list(self.cfg.chain.reviewers)
        if not st.get("reports"):
            with ThreadPoolExecutor(max_workers=max(1, len(roles))) as ex:
                reports = [r for r in ex.map(review, roles) if r is not None]
            if not reports:
                raise Blocked("reviewers: no report came back")
            st["reports"] = [str(r) for r in reports]
            self.ctx.state.save()
            self.ctx.journal.say(f"reviewers: {len(reports)} report(s) received")
        reports = [Path(r) for r in st["reports"]]
        stage = "reviewer-triage"
        conv = self.ctx.pi()
        text = conv.reply_for(stage)
        if text is None:
            note = ("Attached: the referee reports (" + ", ".join(r.name for r in reports) + ") and the paper. The "
                    "referees worked independently of each other and of this conversation.")
            try:
                conv.send(self.ctx.content(self.ctx.prompt("11-referee-triage.md"), reports + ([pdf] if pdf else []),
                                           note=note),
                          stage, reply_file=self.rd / f"{stage}-reply.md", role_name="pi")
            except LLMError as e:
                raise Blocked(f"reviewers: the PI's triage failed: {e}") from e
        self.continue_codex("reviewer-revision", self.rd / f"{stage}-reply.md")
        self.review_loop("final-review", self.cfg.chain.final_review_rounds)
