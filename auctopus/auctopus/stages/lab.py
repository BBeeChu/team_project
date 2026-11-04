"""Stage 'lab': test the theory on the instrument.

1. Feasibility: a fresh feasibility reviewer reads the manuscript and the instrument specification; the PI triages its
   report and ends with LAB-DECISION: GO | NO-GO.
2. After a NO-GO: the manager proposes a design that separates the paper's prediction from its rivals and the PI rules
   on it once. A final NO-GO adds an 'experimental signature' paragraph to the paper and the run moves on.
3. After a GO: the computational researcher builds the digital twin and the run packet (lab_packet/); the PI reviews
   the packet once; one fix pass if needed. LAB-WITHDRAW in that review counts as a NO-GO.
4. Safety: the safety agent reviews the packet against the instrument specification and the laboratory's safety rules
   (SAFETY: APPROVE | REJECT). A rejection gets a correction pass and a second review; a second rejection stops the run.
5. Approval (optional, on by default): a person approves the design with `auctopus approve` before anything reaches
   the instrument.
6. The packet goes to the instrument computer (inbox/<run-id>/) over SSH and the experimentalist runs it, or it goes to
   a shared exchange folder for a hand-run laboratory (transport 'manual'). RUN-RESULT.json reports the outcome.
7. A failed or aborted acquisition can be repeated (chain.lab_reruns) after the PI rules on it, with unchanged criteria.
   An amended packet goes through the safety agent and the approval again before it runs.
8. The returned data go to the HPC (lab_results/); the computational researcher analyses them (15-lab-analysis) and the
   PI reviews the analysis once.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from ..conversation import one_shot
from ..llm import LLMError
from ..remote.agents import RemoteAgent, push_inputs
from ..state import Blocked
from ..util import LOG, atomic_write_text, iso_now, read_json, write_json
from .chain import Chain, decision_line, lab_decision, write_carry_over

PACKET_DOCS = ("README.md", "protocol.md", "results_schema.md")


class AwaitingApproval(Blocked):
    """The run waits for a person to approve the experimental design."""


def safety_verdict(text: str) -> str:
    """The last 'SAFETY: APPROVE | REJECT' line; anything else counts as REJECT (the gate fails closed)."""
    hits = re.findall(r"SAFETY:\s*\**\s*(APPROVED?|REJECT(?:ED)?)\b", text or "", re.IGNORECASE)
    return "APPROVE" if hits and hits[-1].upper().startswith("APPROVE") else "REJECT"


class LabStage(Chain):
    key = "lab"

    @property
    def st(self) -> dict:
        return self.ctx.state.stage(self.key)

    def save(self) -> None:
        self.ctx.state.save()

    # ------------------------------------------------------------------ driver
    def run(self) -> None:
        st = self.st
        if not st.get("decision"):
            st["decision"] = self.feasibility_and_triage()
            self.save()
        if st["decision"] != "GO":
            return
        if not st.get("packet_ok"):
            if not self.build_packet():
                return                               # LAB-WITHDRAW: treated as a NO-GO
            st["packet_ok"] = True
            self.save()
        while not st.get("result_final"):
            # every version of the packet passes the safety agent and the approval before it reaches the instrument
            if self.cfg.lab.safety_review and not st.get("safety_ok"):
                self.safety_review()
                st["safety_ok"] = True
                self.save()
            self.require_approval()
            result = self.run_on_instrument()
            if result["status"] == "done" or not self.rerun_wanted(result):
                st["result_final"] = result
                self.save()
        if not st.get("analysis_done"):
            self.analyse(st["result_final"])
            st["analysis_done"] = True
            self.save()

    # ---------------------------------------------------- 1. feasibility, triage
    def feasibility_and_triage(self) -> str:
        spec = self.cfg.domain("instrument.md")
        card = self.cfg.domain("sample-card.md")
        pdf = self.manuscript_file()             # BENCH: the latest round, or the PI's package when verify is off
        if pdf is None:
            raise Blocked("lab: no manuscript to assess (neither a computational round nor the PI's package)")
        gate_out = self.rd / "lab-feasibility-reply.md"
        note = (f"Attached: the manuscript ({pdf.name}), the setup specification ({spec.name}) and the short "
                f"description of the system ({card.name}).")
        try:
            gate = one_shot(self.cfg, "feasibility",
                            self.ctx.content(self.ctx.prompt("12-feasibility-gate.md"), [pdf, spec, card], note=note),
                            stage="lab-feasibility", out_file=gate_out,
                            record=self.ctx.conv_dir / "lab-feasibility.json").text
        except LLMError as e:
            raise Blocked(f"lab: the feasibility review failed: {e}") from e
        self.ctx.journal.say(f"lab: FEASIBILITY {decision_line(gate, 'FEASIBILITY') or 'unreadable'} (logged only)")
        triage = self.pi_send("lab-triage", "13-feasibility-triage.md", [gate_out, spec, pdf],
                              note=f"Attached: the feasibility report ({gate_out.name}), the setup specification "
                                   f"({spec.name}) and the manuscript ({pdf.name}).")
        decision = lab_decision(triage)
        self.ctx.journal.say(f"lab: LAB-DECISION {decision}")
        if decision != "GO" and self.cfg.chain.manager_redesign:
            decision = self.redesign(pdf, spec)
        if decision != "GO":
            final = (self.rd / "lab-redesign-reply.md") if (self.rd / "lab-redesign-reply.md").exists() else \
                (self.rd / "lab-triage-reply.md")
            atomic_write_text(self.rd / "carry-over-polish.md",
                              "# Experimental signature (the laboratory test was ruled NO-GO)\n\nAdd the short "
                              "experimental-signature paragraph specified below to the manuscript alongside the task "
                              "above; change nothing else.\n\n" + final.read_text(encoding="utf-8"))
            self.ctx.journal.say("lab: NO-GO; the experimental-signature paragraph rides with the next task")
        return decision

    def redesign(self, pdf: Path, spec: Path) -> str:
        """The manager proposes a design that separates the predictions; the PI rules on it once."""
        triage = self.rd / "lab-triage-reply.md"
        gate = self.rd / "lab-feasibility-reply.md"
        mgr_out = self.rd / "lab-manager-design-reply.md"
        try:
            one_shot(self.cfg, "manager",
                     self.ctx.content(self.ctx.prompt("16m-manager-design.md"), [pdf, spec, triage, gate],
                                      note=f"Attached: the manuscript ({pdf.name}), the setup specification "
                                           f"({spec.name}), the PI's triage ({triage.name}) and the feasibility "
                                           f"report ({gate.name})."),
                     stage="lab-manager-design", out_file=mgr_out,
                     record=self.ctx.conv_dir / "lab-manager-design.json")
        except LLMError as e:
            LOG.warning("lab: the manager's design failed (%s); the PI rules without it", e)
        files = [mgr_out] if mgr_out.exists() else []
        reply = self.pi_send("lab-redesign", "16-lab-redesign.md", files,
                             note=("Attached: the manager's proposed design (" + mgr_out.name + ")."
                                   if files else None))
        decision = lab_decision(reply)
        self.ctx.journal.say(f"lab: after the manager's design, LAB-DECISION {decision}")
        if decision == "GO":
            shutil.copyfile(triage, self.rd / "lab-triage-reply.v1-nogo.md")
            shutil.copyfile(self.rd / "lab-redesign-reply.md", triage)
        return decision

    def pi_send(self, stage: str, prompt_name: str, files: list[Path], note: str | None,
                role_name: str = "pi") -> str:
        out = self.rd / f"{stage}-reply.md"
        conv = self.ctx.pi()
        text = conv.reply_for(stage)
        if text is None:
            try:
                text = conv.send(self.ctx.content(self.ctx.prompt(prompt_name), files, note=note), stage,
                                 reply_file=out, role_name=role_name).text
            except LLMError as e:
                raise Blocked(f"lab: PI step {stage} failed: {e}") from e
        elif not out.exists():
            atomic_write_text(out, text)
        return text

    # ---------------------------------------------------------------- 3. packet
    def build_packet(self) -> bool:
        st = self.st
        spec = self.cfg.domain("instrument.md")
        if not st.get("packet_pulled"):
            push_inputs(self.ctx.transport("hpc"), [(spec, f"{self.hpc_dir()}/hardware/instrument.md")])
            self.continue_codex("lab-packet", self.rd / "lab-triage-reply.md", prompt_name="14-lab-twin-packet.md")
            st["packet_pulled"] = True
            self.save()
        round_dir = self.latest_round()
        if not (round_dir / "lab_packet").is_dir():
            raise Blocked("lab: the computational researcher's round has no lab_packet/ folder")
        verdict, out = self.review_once("lab-packet", "14r-lab-packet-review.md", "lab-packet-review", focus="lab")
        text = out.read_text(encoding="utf-8")
        if "LAB-WITHDRAW" in text:
            atomic_write_text(self.rd / "carry-over-polish.md",
                              "# Experimental signature (the PI withdrew the laboratory test)\n\nAdd the "
                              "experimental-signature paragraph specified below to the manuscript; change nothing "
                              "else.\n\n" + text)
            st["decision"] = "WITHDRAWN"
            self.save()
            self.ctx.journal.say("lab: the PI withdrew the laboratory test (LAB-WITHDRAW)")
            return False
        if verdict != "ACCEPT" and not st.get("packet_fixed"):
            self.continue_codex("lab-packet-fix", out)
            st["packet_fixed"] = True
            self.save()
            if not (self.latest_round() / "lab_packet").is_dir():
                raise Blocked("lab: the fixed round has no lab_packet/ folder")
        return True

    # ---------------------------------------------------------------- 4. safety
    def safety_review(self) -> None:
        """The safety agent approves the packet, or a correction pass follows and it reviews again; a rejection after
        the last correction stops the run before anything reaches the instrument."""
        st = self.st
        while True:
            n = st.get("safety_rounds", 0)
            if st.get("safety_fix_pending"):          # a rejection's correction pass (resumable like any task)
                self.continue_codex(f"lab-safety-fix-{n}", self.rd / f"lab-safety-{n}-reply.md")
                if not (self.latest_round() / "lab_packet").is_dir():
                    raise Blocked("lab: the corrected round has no lab_packet/ folder")
                st["safety_fix_pending"] = False
                self.save()
            n += 1
            stage = f"lab-safety-{n}"
            out = self.rd / f"{stage}-reply.md"
            packet = self.latest_round() / "lab_packet"
            docs = [packet / d for d in PACKET_DOCS if (packet / d).exists()]
            spec, rules = self.cfg.domain("instrument.md"), self.cfg.domain("lab-safety.md")
            files = docs + [f for f in (spec, rules) if f.exists()]
            note = ("Attached: the run packet (" + ", ".join(d.name for d in docs) + "), the instrument "
                    f"specification ({spec.name}) and the laboratory's safety rules ({rules.name}).")
            try:
                text = one_shot(self.cfg, "safety", self.ctx.content(self.ctx.prompt("14s-safety-review.md"), files,
                                                                     note=note),
                                stage=stage, out_file=out, record=self.ctx.conv_dir / f"{stage}.json").text
            except LLMError as e:
                raise Blocked(f"lab: the safety review failed: {e}; nothing was sent to the instrument") from e
            verdict = safety_verdict(text)
            st["safety_rounds"] = n
            st["safety_verdict"] = verdict
            self.save()
            self.ctx.journal.say(f"lab: SAFETY {verdict} (review {n})")
            if verdict == "APPROVE":
                return
            if n - st.get("safety_base", 0) > self.cfg.lab.safety_fix_rounds:
                raise Blocked(f"lab: the safety agent rejected the run packet ({out.name}); nothing was sent to the "
                              "instrument")
            st["safety_fix_pending"] = True
            self.save()

    # -------------------------------------------------------------- 5. approval
    def require_approval(self) -> None:
        if not self.cfg.lab.require_approval or self.st.get("approved"):
            return
        packet = self.latest_round() / "lab_packet"
        safety = sorted(self.rd.glob("lab-safety-*-reply.md"))
        note = self.rd / "LAB-APPROVAL-REQUIRED.md"
        atomic_write_text(note, (
            "# The experimental design needs your approval\n\n"
            f"The run packet is in `{packet}` (protocol.md, results_schema.md, analysis/, twin/).\n"
            + (f"The safety agent's review is `{safety[-1]}`.\n" if safety else "")
            + "Nothing has been sent to the instrument. Read the protocol, then approve and continue with:\n\n"
            f"    auctopus approve {self.rd}\n    auctopus resume {self.rd}\n\n"
            f"To decline, run `auctopus resume {self.rd} --from lab` instead: the laboratory stage starts again from "
            "the feasibility review. Edits you make to the packet before approving are sent as they are; the safety "
            "review did not see them.\n"))
        raise AwaitingApproval(f"lab: waiting for approval of the experimental design ({note.name})")

    # ------------------------------------------------------------ 6. instrument
    def run_on_instrument(self) -> dict:
        st = self.st
        attempt = st.setdefault("lab_runs", [])
        current = attempt[-1] if attempt and not attempt[-1].get("finished") else None
        if current is None:
            # the attempt number keeps a repeat from reusing (and overwriting) an earlier run's folders
            run_id = f"{self.rd.name}-{time.strftime('%Y%m%d-%H%M%S')}-run{len(attempt) + 1}"
            current = {"run_id": run_id, "started": iso_now()}
            attempt.append(current)
            self.save()
        run_id = current["run_id"]
        packet = self.latest_round() / "lab_packet"
        if self.cfg.lab.transport == "manual":
            result = self._run_manual(run_id, packet, current)
        else:
            result = self._run_remote(run_id, packet, current)
        current.update({"finished": iso_now(), "status": result.get("status")})
        self.save()
        self.ctx.journal.say(f"lab: acquisition {run_id} returned status {result.get('status')}")
        return {"run_id": run_id, **result}

    def _request(self, run_id: str, packet: Path) -> dict:
        files = [{"path": p.relative_to(packet).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                 for p in sorted(packet.rglob("*")) if p.is_file()]
        return {"run_id": run_id, "paper_run": self.rd.name, "created": iso_now(), "files": files,
                "instructions": "LAB_AGENT_INSTRUCTIONS.md"}

    def _run_remote(self, run_id: str, packet: Path, current: dict) -> dict:
        t = self.ctx.transport("lab")
        root = t.resolve("")
        inbox = f"{root}/inbox/{run_id}"
        outbox = f"{root}/outbox/{run_id}"
        agent = RemoteAgent(self.cfg, "lab", t, root)
        job = current.get("job")
        if not job:
            t.push_dir(packet, inbox)
            t.write_text(f"{inbox}/RUN-REQUEST.json", json.dumps(self._request(run_id, packet), indent=1))
            push_inputs(t, [(self.cfg.domain("lab-agent-instructions.md"), f"{root}/LAB_AGENT_INSTRUCTIONS.md")])
            safety = self.cfg.domain("lab-safety.md")
            rules = [safety.read_text(encoding="utf-8")] if safety.exists() else []
            prompt = self.ctx.prompt("lab-run.md", RUN_ID=run_id)
            job = agent.start(f"lab-{run_id}", prompt, extra_rules=rules)
            current["job"] = job
            self.save()
            self.ctx.journal.say(f"lab: packet sent to the instrument computer as {run_id}; experimentalist started")
        result = agent.wait(job)
        local = self.rd / "lab_results" / run_id
        try:
            t.pull_dir(outbox, local, max_mb=self.cfg.lab.max_pull_mb, include_all=True)   # raw data included
        except Exception as e:  # noqa: BLE001 - a missing outbox is reported as a failed run below
            LOG.error("lab: could not pull %s: %s", outbox, e)
        rr = read_json(local / "RUN-RESULT.json", default=None)
        if rr is None:
            status = "failed" if result.status == "done" else result.status
            rr = {"run_id": run_id, "status": status,
                  "notes": f"no RUN-RESULT.json returned; agent job ended as {result.status} "
                           f"(exit {result.exit_code}). Last output:\n{result.log_tail[-1500:]}"}
            write_json(local / "RUN-RESULT.json", rr)
        return {"status": rr.get("status", "failed"), "local": str(local)}

    def _run_manual(self, run_id: str, packet: Path, current: dict) -> dict:
        exch = self.cfg.path(self.cfg.lab.exchange_dir)
        inbox, outbox = exch / "inbox" / run_id, exch / "outbox" / run_id
        if not inbox.exists():
            shutil.copytree(packet, inbox)
            write_json(inbox / "RUN-REQUEST.json", self._request(run_id, packet))
            shutil.copyfile(self.cfg.domain("lab-agent-instructions.md"), inbox / "LAB_AGENT_INSTRUCTIONS.md")
            self.ctx.journal.say(f"lab: packet written to {inbox}; waiting for {outbox / 'RUN-RESULT.json'}")
        deadline = time.time() + self.cfg.lab.job_timeout_h * 3600
        while True:
            rr = read_json(outbox / "RUN-RESULT.json", default=None)
            if rr and rr.get("status") in ("done", "aborted", "failed"):
                local = self.rd / "lab_results" / run_id
                if local.exists():
                    shutil.rmtree(local)
                shutil.copytree(outbox, local)
                return {"status": rr["status"], "local": str(local)}
            if time.time() > deadline:
                return {"status": "timed-out", "local": ""}
            time.sleep(max(1.0, self.cfg.lab.poll_s))

    # ---------------------------------------------------------------- 7. reruns
    def rerun_wanted(self, result: dict) -> bool:
        st = self.st
        done_reruns = st.get("reruns", 0)
        if result["status"] in ("done", "timed-out") or done_reruns >= self.cfg.chain.lab_reruns:
            return False
        stage = f"lab-rerun-{done_reruns + 1}"
        rr = Path(result.get("local") or ".") / "RUN-RESULT.json"
        files = [p for p in [rr, Path(result.get("local") or ".") / "deviations.md"] if p.exists()]
        reply = self.pi_send(stage, "18-lab-rerun.md", files,
                             note=f"Attached: the laboratory's RUN-RESULT.json and deviations for run "
                                  f"{result['run_id']} (status: {result['status']}).")
        decision = decision_line(reply, "RERUN-DECISION") or "REJECT"
        st["reruns"] = done_reruns + 1
        self.save()
        self.ctx.journal.say(f"lab: RERUN-DECISION {decision} for acquisition {result['run_id']}")
        if decision == "REJECT":
            return False
        if decision.startswith("AMEND"):
            self.continue_codex(f"lab-packet-amend-{done_reruns + 1}", self.rd / f"{stage}-reply.md")
            # the amended packet is a new design: the safety agent and the approval see it again
            st["safety_ok"] = False
            st["safety_base"] = st.get("safety_rounds", 0)
            st["approved"] = False
            self.save()
        return True

    # -------------------------------------------------------------- 8. analysis
    def analyse(self, result: dict) -> None:
        local = Path(result.get("local") or "")
        if local.is_dir():
            push_inputs(self.ctx.transport("hpc"), [(local, f"{self.hpc_dir()}/lab_results")])
        rr = read_json(local / "RUN-RESULT.json", default={"status": result.get("status")}) if local.is_dir() \
            else {"status": result.get("status")}
        task = self.rd / "lab-analysis-task.md"
        atomic_write_text(task, f"# Lab results returned (status: {rr.get('status')})\n\n```json\n"
                                f"{json.dumps(rr, indent=1)}\n```\n")
        self.continue_codex("lab-analysis", task, prompt_name="15-lab-analysis.md")
        verdict, out = self.review_once("lab-analysis", "06-review.md", "lab-analysis-review")
        if verdict == "ACCEPT":
            write_carry_over(self.rd, out)
        elif not self.st.get("analysis_fixed"):
            self.continue_codex("lab-analysis-fix", out)
            self.st["analysis_fixed"] = True
            self.save()
