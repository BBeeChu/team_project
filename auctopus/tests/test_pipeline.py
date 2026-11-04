"""End-to-end runs of the whole pipeline offline: every scenario, the manager's exclusions, the safety agent, the
approval gate, crash and resume, restarting from a stage, and the manual (shared-folder) laboratory route."""
import contextlib
import io
import json
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from auctopus.cli import main as cli_main, scaffold
from auctopus.conversation import Conversation
from auctopus.llm.mock_client import MockClient
from auctopus.pipeline import Pipeline, new_run_dir
from auctopus.util import read_json

from helpers import TempDirMixin, offline_config

SHORT = dict(figures=False, reviewers=[])


def run_pipeline(cfg, run=None, **kw):
    run = run or new_run_dir(cfg, "test")
    return Pipeline(cfg, run, dry_run=True).run(**kw), run


class FullRun(TempDirMixin, unittest.TestCase):
    def test_revision_then_win_runs_every_stage(self):
        cfg = offline_config(self.tmp, "revision-then-win")
        code, run = run_pipeline(cfg)
        self.assertEqual(code, 0)
        state = read_json(run / "state.json")
        for name in ("proposals", "theory", "verify", "verify-review", "lab", "figures", "reviewers", "deliver"):
            self.assertEqual(state["stages"][name]["status"], "done", name)
        batches = state["stages"]["proposals"]["batches"]
        self.assertEqual([b["kind"] for b in batches], ["fresh", "revision"])
        self.assertEqual(state["stages"]["proposals"]["selected"], "02-revision")
        self.assertEqual(read_json(run / "selection.json")["proposal"], "proposer-1")     # the SELECTION line
        self.assertTrue((run / "batches" / "01-fresh" / "prompt.md").exists())
        self.assertTrue((run / "batches" / "02-revision" / "revision" / "seed.md").exists())
        self.assertTrue((run / "pi-verdict.md").exists() and (run / "selection.json").exists())
        self.assertTrue((run / "package" / "main.tex").exists())
        self.assertTrue((run / "delivery-v1" / "main.pdf").exists())
        self.assertTrue((run / "RUN-DONE.json").exists())
        self.assertTrue((run / "lab_results").is_dir())
        # the safety agent approved the packet before the instrument ran it
        self.assertEqual(state["stages"]["lab"]["safety_verdict"], "APPROVE")
        self.assertTrue((run / "lab-safety-1-reply.md").exists())
        # the lab's raw data reached the computational researcher
        hpc_dir = state["hpc"]["dir"]
        remote = Path(cfg.hpc.local_root) / hpc_dir / "lab_results"
        self.assertTrue(any(remote.rglob("raw_counts.npz")))
        # the first review asked for changes: one revision round followed it
        self.assertEqual(state["stages"]["verify-review"]["last_verdict"], "REVISE")
        self.assertTrue(state["stages"]["verify-review-fix1"]["job_pulled"])
        # the PI conversation carries the selection, the theory steps and the reviews in order
        pi = read_json(run / "conversations" / "pi.json")
        stages = [t["stage"] for t in pi["turns"] if t["role"] == "assistant"]
        self.assertEqual(stages[:5], ["selection", "02-proofs", "02b-positioning", "03-write", "04-exp"])
        self.assertTrue((run / "reviewer-claude-report.md").exists() and (run / "reviewer-gpt-report.md").exists())

    def test_never_win_stops(self):
        cfg = offline_config(self.tmp, "never-win", **SHORT)
        cfg.proposals.max_batches = 4
        cfg.proposals.manager_exclusions_after = 0
        code, run = run_pipeline(cfg)
        self.assertEqual(code, 1)
        self.assertIn("no proposal selected", (run / "RUN-BLOCKED.md").read_text(encoding="utf-8"))

    def test_manager_excludes_recurring_families_and_the_pi_relaxes(self):
        cfg = offline_config(self.tmp, "never-win", **SHORT)
        cfg.proposals.max_batches = 5
        cfg.proposals.manager_exclusions_after = 2
        cfg.proposals.relax_after = 4
        code, run = run_pipeline(cfg)
        self.assertEqual(code, 1)
        proposals = read_json(run / "state.json")["stages"]["proposals"]
        self.assertEqual([b["name"] for b in proposals["batches"]],
                         ["01-fresh", "02-revision", "03-fresh", "04-revision", "05-fresh"])
        self.assertEqual([u["after"] for u in proposals["exclusion_updates"]], ["02-revision", "04-revision"])
        added = (run / "exclusions-manager.md").read_text(encoding="utf-8")
        self.assertIn("restate a known estimator", added)
        self.assertNotIn("known estimator", (run / "batches" / "01-fresh" / "prompt.md").read_text("utf-8"))
        self.assertIn("known estimator", (run / "batches" / "03-fresh" / "prompt.md").read_text("utf-8"))
        self.assertTrue((run / "manager" / "exclusions-1" / "verdict-01-fresh.md").exists())
        selection = [b["selection"] for b in proposals["batches"]]
        self.assertEqual(selection, ["strict", "strict", "strict", "relaxed", "relaxed"])

    def test_lab_redo_scenario(self):
        cfg = offline_config(self.tmp, "lab-redo", **SHORT)
        code, run = run_pipeline(cfg)
        self.assertEqual(code, 0)
        stages = read_json(run / "state.json")["stages"]
        lab = stages["lab"]
        self.assertEqual(lab["decision"], "GO")
        self.assertEqual([r["status"] for r in lab["lab_runs"]], ["failed", "done"])
        self.assertTrue((run / "lab-triage-reply.v1-nogo.md").exists())
        self.assertTrue((run / "lab-manager-design-reply.md").exists())
        # the safety agent rejected once, the packet was corrected, the second review approved; the packet amended
        # for the rerun went through a third review before it reached the instrument again
        self.assertEqual((lab["safety_rounds"], lab["safety_verdict"]), (3, "APPROVE"))
        self.assertTrue(stages["lab-safety-fix-1"]["job_pulled"])
        self.assertTrue(stages["lab-packet-amend-1"]["job_pulled"])
        journal = (run / "decisions-journal.md").read_text(encoding="utf-8")
        self.assertLess(journal.index("lab-packet-amend-1"), journal.index("SAFETY APPROVE (review 3)"))
        self.assertLess(journal.index("SAFETY APPROVE (review 3)"), journal.rindex("packet sent to the instrument"))


class SafetyGate(TempDirMixin, unittest.TestCase):
    def test_a_second_safety_rejection_stops_the_run_before_the_instrument(self):
        cfg = offline_config(self.tmp, "win-first", **SHORT)
        real = MockClient.reply

        def always_reject(self, stage, prompt, messages):
            if stage.startswith("lab-safety"):
                return "1. The protocol drives the amplifier without its load.\n\nSAFETY: REJECT"
            return real(self, stage, prompt, messages)

        with mock.patch.object(MockClient, "reply", always_reject):
            code, run = run_pipeline(cfg)
        self.assertEqual(code, 1)
        self.assertIn("safety agent rejected", (run / "RUN-BLOCKED.md").read_text(encoding="utf-8"))
        self.assertFalse((Path(cfg.lab.local_root) / "work" / "inbox").exists())   # nothing reached the lab
        self.assertEqual(read_json(run / "state.json")["stages"]["lab"]["safety_rounds"], 2)


class ApprovalAndResume(TempDirMixin, unittest.TestCase):
    def test_lab_waits_for_approval_then_resumes(self):
        cfg = offline_config(self.tmp, "win-first", **SHORT)
        cfg.lab.require_approval = True
        code, run = run_pipeline(cfg)
        self.assertEqual(code, 2)
        note = (run / "LAB-APPROVAL-REQUIRED.md").read_text(encoding="utf-8")
        self.assertIn("auctopus approve", note)
        self.assertIn("lab-safety-1-reply.md", note)
        self.assertFalse((Path(cfg.lab.local_root) / "work" / "inbox").exists())   # nothing reached the lab
        from auctopus.state import RunState
        st = RunState(run)
        st.stage("lab")["approved"] = True
        st.save()
        code, _ = run_pipeline(cfg, run)
        self.assertEqual(code, 0)
        self.assertTrue((run / "RUN-DONE.json").exists())

    def test_crash_and_resume_never_repeats_paid_steps(self):
        cfg = offline_config(self.tmp, "win-first", **SHORT)
        from auctopus.stages import lab as lab_mod
        orig = lab_mod.LabStage.run_on_instrument
        with mock.patch.object(lab_mod.LabStage, "run_on_instrument", side_effect=RuntimeError("power cut")):
            with self.assertRaises(RuntimeError):
                run_pipeline(cfg)
        run = sorted((self.tmp / "runs").iterdir())[-1]
        state = read_json(run / "state.json")
        self.assertEqual(state["stages"]["lab"]["status"], "blocked")
        pi_before = len(read_json(run / "conversations" / "pi.json")["turns"])
        rounds_before = len(list(run.glob("hpc-round*")))
        calls = []
        real_send = Conversation.send

        def counting_send(self, content, stage, *a, **k):
            calls.append(stage)
            return real_send(self, content, stage, *a, **k)

        with mock.patch.object(Conversation, "send", counting_send):
            code, _ = run_pipeline(cfg, run)
        self.assertEqual(code, 0)
        self.assertNotIn("lab-triage", calls)                  # the PI's triage was not asked again
        self.assertNotIn("lab-packet-review", calls)
        self.assertNotIn("lab-safety-1", calls)                # nor the safety agent
        self.assertEqual(lab_mod.LabStage.run_on_instrument, orig)
        pi_after = read_json(run / "conversations" / "pi.json")["turns"]
        self.assertEqual([t["stage"] for t in pi_after[:pi_before]],
                         [t["stage"] for t in read_json(run / "conversations" / "pi.json")["turns"][:pi_before]])
        self.assertGreater(len(list(run.glob("hpc-round*"))), rounds_before)

    def test_lost_remote_job_is_started_again(self):
        cfg = offline_config(self.tmp, "win-first", **SHORT)
        from auctopus.remote.agents import AgentResult, RemoteAgent
        real_wait = RemoteAgent.wait
        lost = []

        def flaky_wait(self, handle):
            res = real_wait(self, handle)
            if handle["job_id"].startswith("verify-") and not lost:
                lost.append(handle["job_id"])          # the first verification job vanishes (node reboot)
                return AgentResult(None, "lost", "", handle)
            return res

        with mock.patch.object(RemoteAgent, "wait", flaky_wait):
            code, run = run_pipeline(cfg)
        self.assertEqual(code, 0)
        verify = read_json(run / "state.json")["stages"]["verify"]
        self.assertEqual(verify["restarts"], 1)
        self.assertNotEqual(verify["job"]["job_id"], lost[0])
        self.assertTrue(verify["job_pulled"])

    def test_restart_from_a_stage(self):
        cfg = offline_config(self.tmp, "win-first", reviewers=[])
        code, run = run_pipeline(cfg)
        self.assertEqual(code, 0)
        code, _ = run_pipeline(cfg, run, from_stage="figures")
        self.assertEqual(code, 0)
        self.assertTrue((run / "delivery-v2").exists())
        pi = read_json(run / "conversations" / "pi.json")["turns"]
        self.assertEqual(sum(1 for t in pi if t.get("stage") == "figure-plan" and t["role"] == "assistant"), 1)

    def test_skip_and_until(self):
        cfg = offline_config(self.tmp, "win-first", **SHORT)
        code, run = run_pipeline(cfg, until="theory")
        self.assertEqual(code, 0)
        state = read_json(run / "state.json")["stages"]
        self.assertEqual(state["theory"]["status"], "done")
        self.assertNotIn("verify", state)
        code, _ = run_pipeline(cfg, run, skip=["lab"])
        self.assertEqual(code, 0)
        self.assertTrue(read_json(run / "state.json")["stages"]["lab"]["skipped"])


class ManualLab(TempDirMixin, unittest.TestCase):
    def test_shared_folder_route(self):
        cfg = offline_config(self.tmp, "win-first", **SHORT)
        cfg.lab.transport = "manual"
        cfg.lab.exchange_dir = str(self.tmp / "exchange")
        cfg.lab.poll_s = 0.2
        result = {}

        def run():
            result["code"], result["run"] = run_pipeline(cfg)

        th = threading.Thread(target=run)
        th.start()
        inbox = self.tmp / "exchange" / "inbox"
        t0 = time.time()
        while not (inbox.exists() and any(inbox.glob("*/RUN-REQUEST.json"))):
            self.assertLess(time.time() - t0, 120, "the packet never reached the exchange folder")
            time.sleep(0.2)
        req = next(inbox.glob("*/RUN-REQUEST.json"))
        run_id = req.parent.name
        self.assertTrue((req.parent / "protocol.md").exists())
        out = self.tmp / "exchange" / "outbox" / run_id
        (out / "data").mkdir(parents=True)
        (out / "data" / "sweep.csv").write_text("a,b\n")
        (out / "RUN-RESULT.json").write_text(json.dumps({"run_id": run_id, "status": "done"}))
        th.join(timeout=300)
        self.assertFalse(th.is_alive())
        self.assertEqual(result["code"], 0)
        self.assertTrue((result["run"] / "lab_results" / run_id / "data" / "sweep.csv").exists())


class DryRunCommand(TempDirMixin, unittest.TestCase):
    def test_a_dry_run_cannot_be_resumed_or_approved(self):
        # its history comes from mock models: a real configuration must never continue it
        config = str(scaffold(self.tmp, force=True))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli_main(["--config", config, "dry-run", "--scenario", "win-first", "--until", "proposals"])
        self.assertEqual(code, 0)
        run = next((self.tmp / "runs" / "dry-runs").glob("*/runs/*-dry-run"))
        self.assertTrue(read_json(run / "state.json")["dry_run"])
        before = (run / "state.json").read_text(encoding="utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cli_main(["--config", config, "resume", str(run)]), 1)
            self.assertEqual(cli_main(["--config", config, "approve", str(run)]), 1)
        self.assertIn("is a dry run", err.getvalue())
        self.assertEqual((run / "state.json").read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
