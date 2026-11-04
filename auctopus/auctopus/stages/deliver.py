"""Stage 'deliver': copy the final paper and its evidence from the latest round into delivery-vN/, with a checksum
manifest, and mark the run done (RUN-DONE.json)."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from ..state import Blocked
from ..util import atomic_write_text, iso_now, write_json
from .chain import Chain

KEEP_TOP = (".pdf", ".tex", ".bib", ".bbl", ".zip", ".sty", ".cls", ".bst", ".md")   # BENCH: .md manuscripts
KEEP_DOCS = ("EXPERIMENT_REPORT.md", "COMPLETION_AUDIT.md", "completion_manifest.json", "SHA256SUMS", "README.md",
             "ROUND-DONE.json", "REFEREE_RESPONSE.md")


class Deliver(Chain):
    def run(self) -> None:
        round_dir = self.latest_round()
        if round_dir is None:
            raise Blocked("deliver: no round to deliver")
        n = 1
        while (self.rd / f"delivery-v{n}").exists():
            n += 1
        dest = self.rd / f"delivery-v{n}"
        dest.mkdir()
        pdf = self.main_pdf(round_dir)
        tex = self.main_doc(round_dir, self.cfg.chain.manuscript)
        copied: list[Path] = []
        for p in sorted(round_dir.iterdir()):
            if p.is_file() and (p.suffix.lower() in KEEP_TOP or p.name in KEEP_DOCS):
                copied.append(self._copy(p, dest / p.name))
        for f in (pdf, tex):
            if f and not (dest / f.name).exists():
                copied.append(self._copy(f, dest / f.name))
        if tex:
            for sub in ("figures", "fig", "figs", "sections", "images", "report", "results"):   # BENCH: + markdown
                d = tex.parent / sub
                if d.is_dir():
                    shutil.copytree(d, dest / sub, dirs_exist_ok=True)
                    copied += [p for p in (dest / sub).rglob("*") if p.is_file()]
        lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(dest).as_posix()}"
                 for p in sorted(set(copied)) if p.is_file()]
        atomic_write_text(dest / "MANIFEST.sha256", "\n".join(lines) + "\n")
        atomic_write_text(dest / "DELIVERY.md",
                          f"# Delivery v{n}\n\nRun: {self.rd.name}\nSource round: {round_dir.name}\n"
                          f"Final paper: {pdf.name if pdf else '(no PDF)'}\nSource: {tex.name if tex else '(none)'}\n"
                          f"Assembled: {iso_now()}\n\nFiles are listed with SHA-256 checksums in MANIFEST.sha256.\n")
        write_json(self.rd / "RUN-DONE.json", {"run": self.rd.name, "delivery": dest.name,
                                                  "pdf": pdf.name if pdf else None, "when": iso_now()})
        self.ctx.journal.say(f"deliver: {dest.name} assembled (final paper: {pdf.name if pdf else 'no PDF'})")

    @staticmethod
    def _copy(src: Path, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return dst
