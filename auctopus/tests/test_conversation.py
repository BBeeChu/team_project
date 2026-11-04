"""The on-disk conversation: idempotent turns, resuming a running request, cancellation and compaction."""
import unittest
from unittest import mock

from auctopus.conversation import Conversation, one_shot
from auctopus.llm.base import LLMCancelled, LLMReply, TransientLLMError

from helpers import TempDirMixin, offline_config


class FakeClient:
    provider = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def complete(self, messages, *, system, role, stage="", on_started=None, resume_id=None, cancel=None):
        self.calls.append({"messages": [dict(m) for m in messages], "stage": stage, "resume_id": resume_id})
        action = self.script.pop(0)
        if action == "start-then-crash":
            on_started("resp_42")
            raise RuntimeError("process killed")
        if action == "cancel":
            on_started("resp_43")
            raise LLMCancelled("cut")
        if isinstance(action, Exception):
            raise action
        return LLMReply(text=action, provider="fake", model="m")


class ConversationTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.cfg = offline_config(self.tmp)

    def conv(self):
        return Conversation(self.cfg, self.tmp / "c.json", "pi")

    def test_turns_and_reply_for(self):
        fake = FakeClient(["verdict", "proofs"])
        with mock.patch("auctopus.conversation.get_client", return_value=fake):
            c = self.conv()
            c.send("assess this batch", "selection")
            c.send("prove it", "02-proofs")
        c2 = self.conv()
        self.assertEqual(c2.reply_for("selection"), "verdict")
        self.assertEqual([t["role"] for t in c2.turns], ["user", "assistant", "user", "assistant"])
        self.assertEqual(len(fake.calls[1]["messages"]), 3)        # history is sent with every turn

    def test_crash_resumes_the_same_request_without_duplicating_the_turn(self):
        fake = FakeClient(["start-then-crash", "the reply"])
        with mock.patch("auctopus.conversation.get_client", return_value=fake):
            with self.assertRaises(RuntimeError):
                self.conv().send("long question", "selection")
            reply = self.conv().send("long question", "selection")
        self.assertEqual(reply.text, "the reply")
        self.assertEqual(fake.calls[1]["resume_id"], "resp_42")
        turns = self.conv().turns
        self.assertEqual([t["role"] for t in turns], ["user", "assistant"])

    def test_cancelled_request_is_not_resumed(self):
        fake = FakeClient(["cancel", "fresh"])
        with mock.patch("auctopus.conversation.get_client", return_value=fake):
            with self.assertRaises(LLMCancelled):
                self.conv().send("q", "proposer")
            self.conv().send("q", "proposer")
        self.assertIsNone(fake.calls[1]["resume_id"])

    def test_one_shot_record_is_cached(self):
        fake = FakeClient(["first"])
        with mock.patch("auctopus.conversation.get_client", return_value=fake):
            a = one_shot(self.cfg, "feasibility", "q", stage="lab-feasibility", out_file=self.tmp / "o.md",
                         record=self.tmp / "r.json")
            b = one_shot(self.cfg, "feasibility", "q", stage="lab-feasibility", out_file=self.tmp / "o.md",
                         record=self.tmp / "r.json")
        self.assertEqual((a.text, b.text), ("first", "first"))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual((self.tmp / "o.md").read_text(encoding="utf-8"), "first")

    def test_compaction_keeps_recent_turns(self):
        self.cfg.project.max_history_chars = 50
        fake = FakeClient(["a" * 40, "b" * 40, "c" * 40, "SUMMARY", "d"])
        with mock.patch("auctopus.conversation.get_client", return_value=fake):
            c = self.conv()
            for i in range(3):
                c.send(f"q{i} " * 5, f"s{i}")
            c.send("q3", "s3")
        c = self.conv()
        self.assertEqual(c.data["compactions"], 1)
        self.assertIn("SUMMARY", c.turns[0]["content"])
        self.assertEqual(c.reply_for("s3"), "d")
        self.assertTrue(any(p.name.startswith("c.before-compaction") for p in self.tmp.iterdir()))


if __name__ == "__main__":
    unittest.main()
