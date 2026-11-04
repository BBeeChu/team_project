"""Stage 'figures': the PI plans the key figure, the computational researcher builds it, the PI reviews the figure
image alone, one fix; then the other figures are rendered and reviewed as a set, one fix. FIGURE(S): ACCEPT | REVISE."""
from __future__ import annotations

import struct
from pathlib import Path

from ..llm import LLMError
from ..state import Blocked
from ..util import atomic_write_text
from .chain import Chain, figure_verdict


def png_size_mm(path: Path, dpi: float = 600.0) -> tuple[float, float] | None:
    """Physical size of a PNG rendered at `dpi` (the build prompt renders figure1.png at 600 dpi)."""
    try:
        head = path.read_bytes()[:32]
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h = struct.unpack(">II", head[16:24])
        return w / dpi * 25.4, h / dpi * 25.4
    except OSError:
        return None


class Figures(Chain):
    key = "figures"

    def run(self) -> None:
        st = self.ctx.state.stage(self.key)
        if not st.get("plan_done"):
            self._pi("figure-plan", "07-figure-plan.md", "pdf-only", role_name="pi")
            st["plan_done"] = True
            self.ctx.state.save()
        if not st.get("built"):
            self.continue_codex("figure-build", self.rd / "figure-plan-reply.md", prompt_name="07-figure-build.md")
            st["built"] = True
            self.ctx.state.save()
        if not st.get("figure1_reviewed"):
            fig = self.latest_round() / "figure_review" / "figure1.png"
            size = png_size_mm(fig) if fig.exists() else None
            note = "Attached, and deliberately nothing else: the figure and its page preview."
            if size:
                note += f"\n\nFINAL SIZE: {size[0]:.0f} mm wide by {size[1]:.0f} mm high, measured from the render."
            text = self._pi("figure-review1", "08-figure-review.md", "figure1", note=note)
            st["figure1_reviewed"] = True
            st["figure1_verdict"] = figure_verdict(text)
            self.ctx.state.save()
            if st["figure1_verdict"] != "ACCEPT":
                self.continue_codex("figure1-fix", self.rd / "figure-review1-reply.md",
                                    prompt_name="08-figure-fix.md")
        if not st.get("rendered"):
            task = self.rd / "tasks" / "figures-render-task.md"
            atomic_write_text(task, self.ctx.prompt("09-figures-render.md"))
            self.continue_codex("figures-render", task, prompt_name="08-figure-task.md")
            st["rendered"] = True
            self.ctx.state.save()
        if not st.get("all_reviewed"):
            text = self._pi("figures-all-review1", "09-figures-all.md", "figures-all",
                            note="Attached: every figure of the paper with its page preview.")
            st["all_reviewed"] = True
            st["all_verdict"] = figure_verdict(text)
            self.ctx.state.save()
            if st["all_verdict"] != "ACCEPT":
                self.continue_codex("figures-all-fix", self.rd / "figures-all-review1-reply.md",
                                    prompt_name="08-figure-fix.md")

    def _pi(self, stage: str, prompt_name: str, focus: str, note: str | None = None,
            role_name: str = "pi_review") -> str:
        conv = self.ctx.pi()
        text = conv.reply_for(stage)
        if text is not None:
            return text
        round_dir = self.latest_round()
        if round_dir is None:
            raise Blocked(f"figures: nothing to show for {stage}")
        files = self.pick_review_files(round_dir, focus)
        if focus.startswith("figure") and not files:
            raise Blocked(f"figures: the round has no rendered figure for {stage}")
        try:
            return conv.send(self.ctx.content(self.ctx.prompt(prompt_name), files, note=note), stage,
                             reply_file=self.rd / f"{stage}-reply.md", role_name=role_name).text
        except LLMError as e:
            raise Blocked(f"figures: {stage} failed: {e}") from e
