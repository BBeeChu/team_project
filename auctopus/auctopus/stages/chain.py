"""Machinery shared by the stages after the selection: tasks for the computational researcher on the HPC and the PI's
reviews. Each task is pushed as experiment.md (first) or experiment<N>.md, the agent runs to completion, its folder is
pulled into hpc-round<K>, and the PI reviews the round (VERDICT: ACCEPT | REVISE).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..context import Ctx
from ..llm import LLMError
from ..parsing import verdict_line
from ..remote.agents import RemoteAgent, push_inputs
from ..state import Blocked
from ..util import LOG, atomic_write_text, iso_now, slugify

REVIEW_FALLBACK_RE = re.compile(r"verdict\W{0,40}(pass|accept|fail|reject|revise|not\s+(?:yet\s+)?(?:pass|accept))",
                                re.IGNORECASE)
REVIEW_RE = re.compile(r"VERDICT:\s*\**\s*(ACCEPT|REVISE)", re.IGNORECASE)
FIGURE_RE = re.compile(r"FIGURES?:\s*(ACCEPT|REVISE)", re.IGNORECASE)
GENERIC_NAMES = {"main", "paper", "manuscript", "article", "ms", "root"}


def review_verdict(text: str) -> str:
    """The last VERDICT line, else a fallback on the first 1500 characters; anything unclear counts as REVISE."""
    hits = REVIEW_RE.findall(text or "")
    if hits:
        return hits[-1].upper()
    m = REVIEW_FALLBACK_RE.search((text or "")[:1500])
    if m and m.group(1).lower() in ("pass", "accept"):
        return "ACCEPT"
    return "REVISE"


def figure_verdict(text: str) -> str:
    hits = FIGURE_RE.findall(text or "")
    return hits[-1].upper() if hits else "UNKNOWN"


def decision_line(text: str, key: str) -> str | None:
    """'KEY: VALUE' (case-sensitive value, last hit), e.g. LAB-DECISION: GO."""
    hits = re.findall(re.escape(key) + r":\s*\**\s*([A-Z][A-Z -]*[A-Z])", text or "")
    return hits[-1].strip() if hits else None


def lab_decision(text: str) -> str:
    hits = re.findall(r"LAB-DECISION:\s*\**\s*(GO|NO-GO|NOGO|NO GO)", text or "", re.IGNORECASE)
    return "GO" if hits and hits[-1].upper() == "GO" else "NO-GO"


def write_carry_over(run_dir: Path, review: Path) -> None:
    """An ACCEPT review still lists polish items; they ride along with the next codex task (never a round alone)."""
    if not review.exists():
        return
    text = review.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"^\s*\d+\.\s", text, re.M):
        return
    body = ("# Polish items carried over from the last accepted PI review\n\n"
            "Apply the instruction items below ALONGSIDE the task above, in the same pass. They come from a review "
            "that ACCEPTED the previous experiment; treat its instruction list as binding and its verdict as "
            "informational. Never weaken or rerun accepted science to satisfy a wording item.\n\n" + text)
    atomic_write_text(run_dir / "carry-over-polish.md", body)


class Chain:
    """Helpers for stages that drive the computational researcher and ask the PI to review."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.rd = ctx.run_dir

    # ------------------------------------------------------------------- remote
    @property
    def hpc_state(self) -> dict:
        return self.ctx.state.data.setdefault("hpc", {"rounds": [], "experiments": 0})

    def hpc_dir(self) -> str:
        d = self.hpc_state.get("dir")
        if not d:
            d = self.ensure_hpc_dir()        # BENCH: the lab stage may be the first to need the folder (verify off)
        return d

    def ensure_hpc_dir(self) -> str:
        """Create the computational researcher's working folder once: push the manuscript package, the PI's test
        design (experiment.md) when there is one, and the benchmark inputs listed in hpc.inputs."""
        hs = self.hpc_state
        if hs.get("dir"):
            return hs["dir"]
        t = self.ctx.transport("hpc")
        base = self.cfg.hpc.remote_root
        name = self.choose_remote_name()
        remote = f"{base}/{name}"
        for v in range(2, 10):
            if not t.exists(remote):
                break
            remote = f"{base}/{name}-v{v}"
        exp = self.rd / "04-exp-reply.md"
        if exp.exists():
            import shutil
            shutil.copyfile(exp, self.ctx.package / "experiment.md")
        t.push_dir(self.ctx.package, remote)
        for spec in self.cfg.hpc.inputs:           # BENCH: "local:remote" pairs (data folders, reference papers)
            local, _, rel = spec.partition(":")
            src = self.cfg.path(local.strip())
            dst = f"{remote}/{rel.strip() or Path(local).name}"
            if src.is_dir():
                t.push_dir(src, dst)
            elif src.is_file():
                t.push_file(src, dst)
            else:
                LOG.warning("hpc.inputs: %s does not exist; not pushed", src)
        hs["dir"] = remote
        hs["experiments"] = 1 if exp.exists() else 0
        self.ctx.state.save()
        self.ctx.journal.say(f"hpc: package pushed to {remote}" + (f" with {len(self.cfg.hpc.inputs)} input(s)"
                                                                   if self.cfg.hpc.inputs else ""))
        return remote

    def agent(self) -> RemoteAgent:
        return RemoteAgent(self.cfg, "hpc", self.ctx.transport("hpc"), self.hpc_dir())

    def choose_remote_name(self) -> str:
        """First non-generic .pdf/.tex/.zip stem in package/, else paper_<run>."""
        for p in sorted(self.ctx.package.rglob("*")):
            if p.suffix.lower() in (".pdf", ".tex", ".zip") and p.stem.lower() not in GENERIC_NAMES:
                stem = re.sub(r"_(source|package|bundle)$", "", p.stem)
                return slugify(stem, 50)
        return "paper_" + self.rd.name

    # ------------------------------------------------------------------ rounds
    def latest_round(self) -> Path | None:
        rounds = sorted(self.rd.glob("hpc-round*"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0))
        return rounds[-1] if rounds else None

    def pull_round(self) -> Path:
        n = (int(re.sub(r"\D", "", self.latest_round().name)) if self.latest_round() else 0) + 1
        dest = self.rd / f"hpc-round{n}"
        count = self.ctx.transport("hpc").pull_dir(self.hpc_dir(), dest, exclude=self.cfg.hpc.pull_exclude,
                                                  max_mb=self.cfg.hpc.max_pull_mb)
        self.hpc_state["rounds"].append({"round": n, "pulled": iso_now(), "files": count})
        self.ctx.state.save()
        self.ctx.journal.say(f"hpc: pulled round {n} ({count} files)")
        return dest

    def codex_task(self, key: str, prompt: str, task_file: Path | None = None, task_name: str | None = None,
                   inputs: list[tuple[Path, str]] | None = None, apply_carry_over: bool = True) -> Path:
        """Run one codex task to completion and pull the round. Resumable: a task whose job is already running (or
        finished but not pulled) is waited for instead of being started again."""
        st = self.ctx.state.stage(key)
        agent = self.agent()
        job = st.get("job")
        if job and st.get("job_pulled"):
            return Path(st["round_dir"])
        while True:
            if job and st.get("job_result", {}).get("status") in ("lost", "timeout"):
                # the process vanished (node reboot, killed session) or ran out of time: start the task again
                if st.get("restarts", 0) >= 3:
                    raise Blocked(f"{key}: the task failed to finish {st['restarts'] + 1} times")
                st["restarts"] = st.get("restarts", 0) + 1
                st.pop("job_result", None)
                job = None
                self.ctx.journal.say(f"{key}: restarting the task (restart {st['restarts']})")
            if not job:
                pushes = list(inputs or [])
                staged_name = task_name or (task_file.name if task_file else None)
                if task_file is not None:
                    staged = self.rd / "tasks" / staged_name
                    if not (st.get("task_staged") and staged.exists()):     # a restart reuses the staged task
                        text = task_file.read_text(encoding="utf-8")
                        carry = self.rd / "carry-over-polish.md"
                        with_carry = apply_carry_over and carry.exists()
                        if with_carry:
                            text = text.rstrip() + "\n\n" + carry.read_text(encoding="utf-8")
                        atomic_write_text(staged, text)
                        st["task_staged"] = True
                        self.ctx.state.save()
                        if with_carry:
                            carry.rename(self.rd / f"carry-over-polish.applied-{key}.md")
                            self.ctx.journal.say(f"{key}: carry-over polish items appended to the task")
                    pushes.append((staged, f"{self.hpc_dir()}/{staged_name}"))
                    # a fresh `codex exec` has no memory of the last session: name the task file explicitly
                    note = f"The task file for this pass is `{staged_name}` in this folder."
                    if note not in prompt:
                        prompt = prompt.rstrip() + "\n\n" + note
                push_inputs(self.ctx.transport("hpc"), pushes)
                agent.clear_round_marker()
                job_id = f"{key}-{len(self.hpc_state['rounds']) + 1}-{iso_now().replace(':', '').replace('-', '')}"
                if st.get("restarts"):              # a restart may fall in the same second as the lost job
                    job_id += f"-r{st['restarts']}"
                job = agent.start(job_id, prompt)
                st["job"] = job
                self.ctx.state.save()
                self.ctx.journal.say(f"{key}: computational researcher started ({job_id})")
            result = agent.wait(job)
            done = agent.round_done()
            st["job_result"] = {"exit_code": result.exit_code, "status": result.status,
                                "round_done": done.get("status") if done else None}
            self.ctx.state.save()
            if result.status == "done":
                break
            if st.get("restarts", 0) >= 1:
                raise Blocked(f"{key}: the computational researcher's job ended as '{result.status}'. Last "
                              f"output:\n{result.log_tail[-2000:]}")
        if result.exit_code not in (0, None):
            LOG.warning("%s: agent exited with code %s; pulling what it produced", key, result.exit_code)
        if not done:
            LOG.warning("%s: the agent left no ROUND-DONE.json; treating the finished process as the end", key)
        round_dir = self.pull_round()
        st["job_pulled"] = True
        st["round_dir"] = str(round_dir)
        self.ctx.state.save()
        return round_dir

    def next_experiment_name(self) -> str:
        n = self.hpc_state.get("experiments", 0) + 1
        self.hpc_state["experiments"] = n
        self.ctx.state.save()
        return "experiment.md" if n == 1 else f"experiment{n}.md"

    def continue_codex(self, key: str, task_file: Path, prompt_name: str = "05-continue.md") -> Path:
        st = self.ctx.state.stage(key)
        name = st.get("task_name")
        if not name:
            name = self.next_experiment_name()
            st["task_name"] = name
            self.ctx.state.save()
        prompt = self.ctx.prompt(prompt_name, TASK_FILE=name)
        return self.codex_task(key, prompt, task_file=task_file, task_name=name)

    # ----------------------------------------------------------------- reviews
    def pick_review_files(self, round_dir: Path, focus: str = "manuscript") -> list[Path]:
        """The files the PI sees for a review: the main PDF first, then the source, audits and responses; at most
        review_max_files files."""
        limit = self.cfg.chain.review_max_files
        if focus == "figure1":
            return [p for p in (round_dir / "figure_review" / "figure1.png",
                                round_dir / "figure_review" / "page_figure1.png") if p.exists()]
        if focus == "figures-all":
            figs = sorted(p for p in round_dir.rglob("*.png")
                          if re.match(r"(page_)?figure\d+", p.stem) and p.stem not in ("figure1", "page_figure1"))
            return figs[:limit]
        pdf = self.main_pdf(round_dir)
        doc = self.main_doc(round_dir, self.cfg.chain.manuscript)
        picks: list[Path] = [p for p in (pdf, doc) if p]       # the PDF first, then the source (or the Markdown)
        if focus == "pdf-only":
            return picks[:1]
        if focus == "lab":
            lp = round_dir / "lab_packet"
            for rel in ("README.md", "protocol.md", "results_schema.md", "twin/report.md", "completion_manifest.json",
                        "progress.json", "implementation_plan.md"):
                if (lp / rel).exists():
                    picks.append(lp / rel)
            return picks[:limit]
        top = sorted(p for p in round_dir.iterdir() if p.is_file())
        patterns = [r"FINAL_AUDIT\.json$", r"RESPONSE.*\.md$", r"AUDIT.*\.md$", r"\.listing\.txt$",
                    r"ROUND-DONE\.json$", r"REPORT.*\.md$", r"results?\.md$", r"\.md$", r"\.(json|csv|txt)$"]
        for pat in patterns:
            for p in top:
                if len(picks) >= limit:
                    break
                if p in picks or re.match(r"experiment\d*\.md$", p.name) or p.name in (
                        "NOTES-RESUME.md", "PULL-SKIPPED.txt"):
                    continue
                if re.search(pat, p.name, re.IGNORECASE):
                    picks.append(p)
        return picks[:limit]

    @staticmethod
    def main_pdf(round_dir: Path) -> Path | None:
        for name in ("main.pdf", "manuscript.pdf", "paper.pdf"):
            hits = sorted(round_dir.rglob(name), key=lambda p: len(p.parts))
            if hits:
                return hits[0]
        pdfs = sorted(round_dir.glob("*.pdf")) or sorted(round_dir.rglob("*.pdf"), key=lambda p: len(p.parts))
        return pdfs[0] if pdfs else None

    @staticmethod
    def main_doc(round_dir: Path, manuscript: str = "latex") -> Path | None:
        """BENCH: the manuscript source: main.tex for LaTeX, else the main Markdown document."""
        if manuscript != "markdown":
            return Chain.main_tex(round_dir)
        for rel in ("main.md", "manuscript.md", "paper.md", "report/report.md", "report.md"):
            hits = sorted(round_dir.rglob(rel), key=lambda p: len(p.parts))
            hits = [h for h in hits if ".auctopus" not in h.parts and "lab_packet" not in h.parts]
            if hits:
                return hits[0]
        return None

    def manuscript_file(self) -> Path | None:
        """BENCH: the manuscript to review or assess: the latest round's PDF, else its main document, else the
        PI's package (when no computational round exists yet)."""
        round_dir = self.latest_round()
        if round_dir is not None:
            found = self.main_pdf(round_dir) or self.main_doc(round_dir, self.cfg.chain.manuscript)
            if found:
                return found
        return self.main_doc(self.ctx.package, self.cfg.chain.manuscript)

    @staticmethod
    def main_tex(round_dir: Path) -> Path | None:
        for name in ("main.tex", "manuscript.tex", "paper.tex"):
            hits = sorted(round_dir.rglob(name), key=lambda p: len(p.parts))
            if hits:
                return hits[0]
        texs = [p for p in round_dir.rglob("*.tex") if "\\documentclass" in p.read_text(encoding="utf-8",
                                                                                         errors="replace")]
        return sorted(texs, key=lambda p: len(p.parts))[0] if texs else None

    def review_once(self, key: str, prompt_name: str, out_stem: str, focus: str = "manuscript",
                    role_name: str = "pi_review", extra_note: str = "") -> tuple[str, Path]:
        """One PI review of the latest round. Idempotent: an existing reply file is reused."""
        out = self.rd / f"{out_stem}-reply.md"
        conv = self.ctx.pi()
        text = conv.reply_for(out_stem)
        if text is None:
            round_dir = self.latest_round()
            if round_dir is None:
                raise Blocked(f"{key}: nothing to review (no round pulled)")
            files = self.pick_review_files(round_dir, focus)
            names = ", ".join(f.name for f in files) or "(none)"
            note = f"The attached files are the agent's revised manuscript and experimental results: {names}."
            if extra_note:
                note += "\n\n" + extra_note
            self.ctx.journal.say(f"{key}: PI review ({prompt_name}, {len(files)} attachment(s))")
            try:
                text = conv.send(self.ctx.content(self.ctx.prompt(prompt_name), files, note=note), out_stem,
                                 reply_file=out, role_name=role_name).text
            except LLMError as e:
                raise Blocked(f"{key}: the PI review failed: {e}") from e
        elif not out.exists():
            atomic_write_text(out, text)
        verdict = review_verdict(text)
        self.ctx.journal.say(f"{key}: review verdict {verdict}")
        return verdict, out

    def review_loop(self, key: str, max_rounds: int) -> None:
        """Review once (default): one PI review; ACCEPT carries its polish items over to the next task, REVISE gets one
        revision pass by the computational researcher and the paper moves on. In 'until-accept' mode the loop repeats
        and stops the run if it never accepts."""
        st = self.ctx.state.stage(key)
        limit = 1 if self.cfg.chain.review_mode == "once" else max_rounds
        while True:
            rounds = st.get("rounds", 0)
            if st.get("phase") == "codex":
                self.continue_codex(f"{key}-fix{rounds}", Path(st["last_review"]))
                st["phase"] = "review"
                if self.cfg.chain.review_mode == "once":
                    st["applied_once"] = True
                    self.ctx.state.save()
                    return
                self.ctx.state.save()
            if rounds >= limit:
                if self.cfg.chain.review_mode == "once":
                    return
                raise Blocked(f"{key}: not accepted after {rounds} review rounds")
            verdict, out = self.review_once(key, "06-review.md", f"{key}-round{rounds + 1}")
            st["rounds"] = rounds + 1
            st["last_verdict"] = verdict
            st["last_review"] = str(out)
            if verdict == "ACCEPT":
                write_carry_over(self.rd, out)
                st["phase"] = "done"
                self.ctx.state.save()
                return
            st["phase"] = "codex"
            self.ctx.state.save()
