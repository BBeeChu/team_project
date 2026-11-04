"""The front of the pipeline: proposal batches until the PI selects one, then the PI's theory steps.

proposals: fresh batches of independent proposers; deduplication; the PI's verdict on the batch (strict or relaxed);
a revision batch that develops the PI's BEST SEED; the manager's exclusions after repeated batches without a selection.
Decision rules: a reply under 400 characters (or under 600 with an error phrase) is junk, but refusals survive and reach
dedup and the PI; the early cut counts only replies of at least `refusal_min_words` words; dedup fails open; the last
SELECTION line decides (a verdict without one selects a proposal unless the no-selection pattern appears in its first
1200 characters); the last BEST SEED line wins; revision is one level deep (a revision batch is never revised again)
and its brief carries no exclusion list.

theory: proofs, positioning, the LaTeX manuscript (delivered as file blocks) and the computational test design, all in
the PI's conversation.
"""
from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..context import Ctx
from ..conversation import Conversation, one_shot
from ..llm import LLMError
from ..llm.base import LLMCancelled
from ..parsing import (FILE_PROTOCOL, best_seed, extract_files, is_junk_reply, is_proposal, parse_keep, pi_selected,
                       save_files, selected_proposer)
from ..prompt_builder import exclusion_clauses, pi_select_prompt, proposer_prompts
from ..state import Blocked
from ..util import LOG, atomic_write_text, iso_now, write_json

MANAGER_EXCLUSIONS = "exclusions-manager.md"     # the manager's additions to the exclusion list, in the run folder


class Proposals:
    """Stage 'proposals': run batches until the PI selects a proposal."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.cfg = ctx.cfg

    @property
    def st(self) -> dict:
        return self.ctx.state.stage("proposals")

    # ------------------------------------------------------------------ driver
    def run(self) -> None:
        st = self.st
        batches: list[dict] = st.setdefault("batches", [])
        while not st.get("selected"):
            if batches and batches[-1].get("status") == "running":
                batch = batches[-1]                          # resume an interrupted batch
                self.ctx.journal.say(f"proposals: resuming batch {batch['name']}")
            else:
                if len(batches) >= self.cfg.proposals.max_batches:
                    raise Blocked(f"no proposal selected after {len(batches)} batches "
                                  f"(proposals.max_batches = {self.cfg.proposals.max_batches})")
                batch = self._next_batch(batches)
                if batch["kind"] == "fresh":
                    self._maybe_manager_exclusions(batches)
                batches.append(batch)
                self.ctx.state.save()
                self.ctx.journal.say(f"proposals: batch {batch['name']} started"
                                     + (f" (revision of {batch['source']} {batch['seed']})"
                                        if batch["kind"] == "revision" else ""))
            result = self._run_batch(batch, len(batches))
            batch.update(result)
            batch["status"] = "selected" if result["selected"] else result.get("status", "none-selected")
            batch["finished"] = iso_now()
            self.ctx.state.save()
            if result["selected"]:
                st["selected"] = batch["name"]
                self._promote(batch)
                self.ctx.state.save()
                self.ctx.journal.say(f"proposals: the PI selected {result.get('proposal') or 'a proposal'} in batch "
                                     f"{batch['name']}")
            else:
                self.ctx.journal.say(f"proposals: batch {batch['name']} ended without a selection "
                                     f"({batch['status']}; best seed: {result.get('seed') or 'none'})")

    def _next_batch(self, batches: list[dict]) -> dict:
        idx = len(batches) + 1
        last = batches[-1] if batches else None
        if (last and self.cfg.proposals.revision and last.get("kind") == "fresh"
                and last.get("status") == "none-selected" and last.get("seed")):
            return {"name": f"{idx:02d}-revision", "kind": "revision", "source": last["name"], "seed": last["seed"],
                    "status": "running", "started": iso_now()}
        return {"name": f"{idx:02d}-fresh", "kind": "fresh", "status": "running", "started": iso_now()}

    def _bdir(self, name: str) -> Path:
        p = self.ctx.run_dir / "batches" / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------- the manager's exclusions
    def _maybe_manager_exclusions(self, batches: list[dict]) -> None:
        """After `manager_exclusions_after` batches in a row without a selection, the manager reads the PI's verdicts
        and excludes the idea families rejected again and again from the following fresh batches."""
        every = self.cfg.proposals.manager_exclusions_after
        updates: list[dict] = self.st.setdefault("exclusion_updates", [])
        names = [b["name"] for b in batches]
        start = names.index(updates[-1]["after"]) + 1 if updates and updates[-1]["after"] in names else 0
        since = batches[start:]                  # every earlier batch ended without a selection (the loop is running)
        if every <= 0 or len(since) < every:
            return
        n = len(updates) + 1
        stage = f"manager-exclusions-{n}"
        mdir = self.ctx.run_dir / "manager" / f"exclusions-{n}"
        mdir.mkdir(parents=True, exist_ok=True)
        verdicts = []
        for b in since:
            src = self._bdir(b["name"]) / "pi-verdict.md"
            if src.exists():
                verdicts.append(mdir / f"verdict-{b['name']}.md")
                shutil.copyfile(src, verdicts[-1])
        if not verdicts:
            return
        brief = mdir / "proposer-brief.md"
        atomic_write_text(brief, proposer_prompts(self.cfg, self.manager_exclusions())[0])
        note = (f"Attached: the PI's verdicts on the last {len(verdicts)} batches ("
                + ", ".join(v.name for v in verdicts) + ") and the brief the fresh proposers receive now "
                "(proposer-brief.md).")
        out = mdir / "manager-reply.md"
        self.ctx.journal.say(f"proposals: {len(since)} batches without a selection; the manager reviews the verdicts")
        try:
            reply = one_shot(self.cfg, "manager", self.ctx.content(self.ctx.prompt("manager-exclusions.md"),
                                                                   verdicts + [brief], note=note),
                             stage=stage, out_file=out, record=self.ctx.conv_dir / f"{stage}.json").text
        except LLMError as e:
            LOG.warning("the manager's exclusion review failed (%s); the exclusion list stays as it is", e)
            reply = ""
        added = (extract_files(reply).get("exclusions.md") or "").strip()
        if added:
            path = self.ctx.run_dir / MANAGER_EXCLUSIONS
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            atomic_write_text(path, exclusion_clauses(old, added) + "\n")
            self.ctx.journal.say(f"proposals: the manager added exclusions for the next fresh batches ({path.name})")
        else:
            self.ctx.journal.say("proposals: the manager added no exclusions")
        updates.append({"after": batches[-1]["name"], "stage": stage, "added": bool(added), "at": iso_now()})
        self.ctx.state.save()

    def manager_exclusions(self) -> str:
        path = self.ctx.run_dir / MANAGER_EXCLUSIONS
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # ------------------------------------------------------------------- batch
    def _run_batch(self, batch: dict, index: int) -> dict:
        bdir = self._bdir(batch["name"])
        files: list[Path] = []
        if batch["kind"] == "fresh":
            prompt_file = bdir / "prompt.md"
            if not prompt_file.exists():           # the brief is fixed when the batch starts (stable across resumes)
                atomic_write_text(prompt_file, proposer_prompts(self.cfg, self.manager_exclusions())[0])
            prompt = prompt_file.read_text(encoding="utf-8")
            n = self.cfg.proposals.proposers
        else:
            src = self._bdir(batch["source"])
            rdir = bdir / "revision"
            rdir.mkdir(exist_ok=True)
            if not (rdir / "brief.md").exists():
                atomic_write_text(rdir / "brief.md", proposer_prompts(self.cfg)[1])
            shutil.copyfile(src / f"{batch['seed']}.md", rdir / "seed.md")
            shutil.copyfile(src / "pi-verdict.md", rdir / "review.md")
            prompt = self.ctx.prompt("17-revision.md", SEED=batch["seed"])
            files = [rdir / "brief.md", rdir / "seed.md", rdir / "review.md"]
            n = self.cfg.proposals.revision_proposers
        proposers = self._proposers(bdir, prompt, files, n)
        manifest = {"batch": batch["name"], "kind": batch["kind"], "proposers": proposers,
                    "started": batch.get("started")}
        names = [w["file"] for w in proposers if w["status"] == "ok"]
        if not names:
            manifest["result"] = "no-replies"
            write_json(bdir / "manifest.json", manifest)
            errors = [w.get("error", "") for w in proposers if w["status"] == "failed"]
            if errors and len(errors) == len(proposers):
                # every proposer failed outright (wrong key, unknown model, quota): another batch would too
                raise Blocked(f"every proposer failed; first error: {errors[0]}")
            return {"selected": False, "status": "no-replies"}
        kept = names
        if batch["kind"] == "fresh" and self.cfg.proposals.dedup and len(names) >= 2:
            kept = self._dedup(bdir, names)
            manifest["dedup"] = {"kept": kept, "removed": [x for x in names if x not in kept]}
        relaxed = self.relaxed(index)
        verdict = self._assess(bdir, kept, relaxed)
        selected = pi_selected(verdict)
        seed = None if selected else best_seed(verdict)
        manifest.update({"assessed": kept, "selection": "relaxed" if relaxed else "strict", "selected": selected,
                         "seed": seed, "proposal": selected_proposer(verdict), "finished": iso_now()})
        write_json(bdir / "manifest.json", manifest)
        return {"selected": selected, "seed": seed, "proposal": manifest["proposal"], "assessed": kept,
                "selection": manifest["selection"], "status": "selected" if selected else "none-selected"}

    def relaxed(self, index: int) -> bool:
        """Relaxed selection for this batch: always in relaxed mode, from batch `relax_after` on in strict mode."""
        pc = self.cfg.proposals
        return pc.selection == "relaxed" or (pc.relax_after > 0 and index >= pc.relax_after)

    def _proposers(self, bdir: Path, prompt: str, files: list[Path], n: int) -> list[dict]:
        pc = self.cfg.proposals
        cut = threading.Event()
        lock = threading.Lock()
        count = [0]
        content = self.ctx.content(prompt, files)
        conv_dir = bdir / "conversations"
        conv_dir.mkdir(exist_ok=True)
        # proposals that already exist (a resumed batch) count toward the early cut
        for i in range(1, n + 1):
            p = bdir / f"proposer-{i}.md"
            if p.exists() and is_proposal(p.read_text(encoding="utf-8"), pc.refusal_min_words):
                count[0] += 1
        if pc.assess_after and count[0] >= pc.assess_after:
            cut.set()

        def work(i: int) -> dict:
            label = f"proposer-{i}"
            out = bdir / f"{label}.md"
            if out.exists():
                return {"label": label, "status": "ok", "file": out.name, "resumed": True}
            if cut.is_set():
                return {"label": label, "status": "cut"}
            t0 = time.monotonic()
            try:
                reply = one_shot(self.cfg, "proposer", content, stage="proposer", record=conv_dir / f"{label}.json",
                                 cancel=cut)
            except LLMCancelled:
                return {"label": label, "status": "cut"}
            except LLMError as e:
                LOG.warning("%s failed: %s", label, e)
                return {"label": label, "status": "failed", "error": str(e)[:500]}
            text = reply.text
            if is_junk_reply(text):
                return {"label": label, "status": "junk", "chars": len(text)}
            atomic_write_text(out, text)
            with lock:
                if is_proposal(text, pc.refusal_min_words):
                    count[0] += 1
                    if pc.assess_after and count[0] >= pc.assess_after and not cut.is_set():
                        LOG.info("%d proposals are in: stopping the remaining proposers", count[0])
                        cut.set()
            return {"label": label, "status": "ok", "file": out.name, "seconds": round(time.monotonic() - t0, 1),
                    "words": len(text.split()), "model": reply.model}

        results: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=max(1, pc.concurrency)) as ex:
            futures = {}
            for i in range(1, n + 1):
                if cut.is_set() and not (bdir / f"proposer-{i}.md").exists():
                    results[i] = {"label": f"proposer-{i}", "status": "cut"}
                    continue
                futures[ex.submit(work, i)] = i
                if pc.stagger_s and i < n and not cut.is_set():
                    time.sleep(pc.stagger_s)
            for f in as_completed(futures):
                results[futures[f]] = f.result()
        ordered = [results[i] for i in sorted(results)]
        ok = sum(1 for r in ordered if r["status"] == "ok")
        LOG.info("proposers: %d replies kept, %d cut, %d failed, %d junk", ok,
                 sum(r["status"] == "cut" for r in ordered), sum(r["status"] == "failed" for r in ordered),
                 sum(r["status"] == "junk" for r in ordered))
        return ordered

    def _dedup(self, bdir: Path, names: list[str]) -> list[str]:
        note = "The proposals are attached as markdown files: " + ", ".join(names) + "."
        try:
            reply = one_shot(self.cfg, "dedup", self.ctx.content(self.ctx.prompt("dedup.md"),
                                                                [bdir / n for n in names], note=note),
                             stage="dedup", out_file=bdir / "dedup-reply.md",
                             record=bdir / "conversations" / "dedup.json")
        except LLMError as e:
            LOG.warning("dedup failed (%s): keeping every proposal", e)
            return names
        kept = parse_keep(reply.text, names)
        if kept is None:
            LOG.warning("dedup reply has no usable KEEP line: keeping every proposal")
            return names
        return kept

    def _assess(self, bdir: Path, kept: list[str], relaxed: bool) -> str:
        conv = Conversation(self.cfg, bdir / "conversations" / "pi.json", "pi")
        done = conv.reply_for("selection")
        if done is not None:
            return done
        note = "The proposals to evaluate are attached as markdown files: " + ", ".join(kept) + "."
        content = self.ctx.content(pi_select_prompt(self.cfg, relaxed=relaxed), [bdir / k for k in kept], note=note)
        try:
            return conv.send(content, "selection", reply_file=bdir / "pi-verdict.md").text
        except LLMError as e:
            raise Blocked(f"the PI's verdict failed: {e}") from e

    def _promote(self, batch: dict) -> None:
        """The selecting batch's PI conversation becomes the PI conversation of the whole run."""
        bdir = self._bdir(batch["name"])
        pi = self.ctx.conv_dir / "pi.json"
        if not pi.exists():
            shutil.copyfile(bdir / "conversations" / "pi.json", pi)
        shutil.copyfile(bdir / "pi-verdict.md", self.ctx.run_dir / "pi-verdict.md")
        write_json(self.ctx.run_dir / "selection.json", {"batch": batch["name"], "kind": batch["kind"],
                                                         "proposal": batch.get("proposal"),
                                                         "source": batch.get("source"), "when": iso_now()})


class Theory:
    """Stage 'theory': proofs, positioning, the manuscript and the computational test design, in the PI's
    conversation."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.cfg = ctx.cfg

    def run(self) -> None:
        conv = self.ctx.pi()
        if not conv.turns:
            raise Blocked("no PI conversation: the proposals stage has not selected a proposal")
        for name in self.cfg.chain.theory_steps:
            self._send(conv, name)
        if not self._manuscript_delivered():
            self.ctx.journal.say("theory: no manuscript source received; asking the PI to deliver it as files")
            self._send(conv, "03b-redeliver")
            if not self._manuscript_delivered():
                raise Blocked("the PI's manuscript reply carried no manuscript file, even after the redelivery "
                              "request")
        if not (self.ctx.run_dir / "04-exp-reply.md").exists():
            raise Blocked("no computational test design (04-exp-reply.md)")

    def _manuscript_delivered(self) -> bool:
        """BENCH: a .tex file for LaTeX manuscripts, or the main Markdown document (main.md, report/report.md, ...)
        when chain.manuscript = "markdown"."""
        if self.cfg.chain.manuscript == "markdown":
            from .chain import Chain
            return Chain.main_doc(self.ctx.package, "markdown") is not None
        return bool(list(self.ctx.package.rglob("*.tex")))

    def _send(self, conv: Conversation, name: str) -> None:
        reply = conv.reply_for(name)
        if reply is None:
            prompt = self.ctx.prompt(f"{name}.md")
            if name in self.cfg.chain.file_steps:
                prompt = prompt.rstrip() + "\n" + FILE_PROTOCOL
            self.ctx.journal.say(f"theory: {name}")
            try:
                reply = conv.send(prompt, name, reply_file=self.ctx.run_dir / f"{name}-reply.md").text
            except LLMError as e:
                raise Blocked(f"theory step {name} failed: {e}") from e
        elif not (self.ctx.run_dir / f"{name}-reply.md").exists():
            atomic_write_text(self.ctx.run_dir / f"{name}-reply.md", reply)
        files = extract_files(reply)
        if files:
            save_files(files, self.ctx.package)
            LOG.info("%s: %d file(s) saved to package/: %s", name, len(files), ", ".join(sorted(files)))
