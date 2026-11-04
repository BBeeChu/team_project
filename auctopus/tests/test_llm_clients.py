"""The OpenAI and Anthropic clients against fake SDK objects: request shapes, background polling and resume,
cancellation, retries, refusals, server-side fallbacks, paused turns and attachments."""
import threading
import unittest
from types import SimpleNamespace as NS

from auctopus.config import RoleCfg
from auctopus.llm.anthropic_client import FALLBACK_BETA, AnthropicClient
from auctopus.llm.base import LLMCancelled, LLMRefusal
from auctopus.llm.openai_client import OpenAIClient

from helpers import TempDirMixin


# ------------------------------------------------------------------------------------------------- fake OpenAI
class FakeResponses:
    def __init__(self, statuses=("completed",), text="hello", fail_first=None, incomplete=None):
        self.statuses = list(statuses)
        self.text = text
        self.created, self.retrieved, self.cancelled = [], [], []
        self.fail_first = fail_first
        self.incomplete = incomplete

    def _resp(self, rid, status):
        err = NS(code=self.fail_first, message="slow down") if status == "failed" else None
        details = NS(reason=self.incomplete) if status == "incomplete" else None
        return NS(id=rid, status=status, output_text=self.text if status in ("completed", "incomplete") else "",
                  model="gpt-test", usage=NS(model_dump=lambda: {"input_tokens": 3}), error=err,
                  incomplete_details=details)

    def create(self, **kw):
        self.created.append(kw)
        rid = f"resp_{len(self.created)}"
        if self.fail_first and len(self.created) == 1:
            return self._resp(rid, "failed")
        if kw.get("extra_body", {}).get("background"):
            return self._resp(rid, "queued")
        return self._resp(rid, "incomplete" if self.incomplete else "completed")

    def retrieve(self, rid):
        self.retrieved.append(rid)
        status = self.statuses.pop(0) if self.statuses else "completed"
        if self.incomplete and status == "completed":
            status = "incomplete"
        return self._resp(rid, status)

    def cancel(self, rid):
        self.cancelled.append(rid)


class FakeOpenAI:
    def __init__(self, responses):
        self.responses = responses

    def with_options(self, **kw):
        return self


def role(**kw):
    base = dict(provider="openai", model="gpt-test", effort="high", max_attempts=2, backoff_s=[0.0], poll_s=0.01,
                timeout_s=30)
    base.update(kw)
    return RoleCfg(**base)


class OpenAI(TempDirMixin, unittest.TestCase):
    def test_plain_request_shape(self):
        r = FakeResponses()
        c = OpenAIClient("k", sdk_client=FakeOpenAI(r))
        rep = c.complete([{"role": "user", "content": "hi"}], system="sys", role=role(web_search=True), stage="t")
        kw = r.created[0]
        self.assertEqual(kw["model"], "gpt-test")
        self.assertEqual(kw["instructions"], "sys")
        self.assertEqual(kw["reasoning"], {"effort": "high"})
        self.assertEqual(kw["tools"], [{"type": "web_search"}])
        self.assertEqual(kw["max_output_tokens"], 64000)
        self.assertEqual(rep.text, "hello")
        r2 = FakeResponses()
        OpenAIClient("k", sdk_client=FakeOpenAI(r2)).complete([{"role": "user", "content": "hi"}], system=None,
                                                              role=role(max_output_tokens=0))
        self.assertNotIn("max_output_tokens", r2.created[0])     # 0 = the provider's own limit

    def test_background_polls_and_reports_its_id(self):
        r = FakeResponses(statuses=["in_progress", "in_progress", "completed"])
        c = OpenAIClient("k", sdk_client=FakeOpenAI(r))
        seen = []
        rep = c.complete([{"role": "user", "content": "hi"}], system=None, role=role(background=True), stage="t",
                         on_started=seen.append)
        self.assertEqual(seen, ["resp_1"])
        self.assertTrue(r.created[0]["store"])
        self.assertEqual(len(r.retrieved), 3)
        self.assertEqual(rep.response_id, "resp_1")

    def test_resume_polls_without_creating(self):
        r = FakeResponses()
        c = OpenAIClient("k", sdk_client=FakeOpenAI(r))
        rep = c.complete([], system=None, role=role(background=True), resume_id="resp_77")
        self.assertEqual(r.created, [])
        self.assertEqual(r.retrieved, ["resp_77"])
        self.assertEqual(rep.text, "hello")

    def test_unusable_resumed_response_gets_a_new_request(self):
        r = FakeResponses(statuses=["cancelled"])
        c = OpenAIClient("k", sdk_client=FakeOpenAI(r))
        rep = c.complete([{"role": "user", "content": "x"}], system=None, role=role(), resume_id="resp_old")
        self.assertEqual(r.retrieved, ["resp_old"])
        self.assertEqual(len(r.created), 1)                   # a fresh request replaced the cancelled one
        self.assertEqual(rep.text, "hello")

    def test_cancel_stops_polling_and_cancels_the_response(self):
        r = FakeResponses(statuses=["in_progress"] * 1000)
        c = OpenAIClient("k", sdk_client=FakeOpenAI(r))
        ev = threading.Event()
        ev.set()
        with self.assertRaises(LLMCancelled):
            c.complete([{"role": "user", "content": "x"}], system=None, role=role(background=True), cancel=ev)
        self.assertEqual(r.cancelled, ["resp_1"])

    def test_transient_failure_is_retried_with_a_new_request(self):
        r = FakeResponses(fail_first="rate_limit_exceeded")
        c = OpenAIClient("k", sdk_client=FakeOpenAI(r))
        rep = c.complete([{"role": "user", "content": "x"}], system=None, role=role())
        self.assertEqual(len(r.created), 2)
        self.assertEqual(rep.text, "hello")

    def test_incomplete_replies(self):
        r = FakeResponses(incomplete="max_output_tokens")
        rep = OpenAIClient("k", sdk_client=FakeOpenAI(r)).complete([{"role": "user", "content": "x"}], system=None,
                                                                   role=role())
        self.assertTrue(rep.truncated)
        r2 = FakeResponses(incomplete="content_filter")
        with self.assertRaises(LLMRefusal):
            OpenAIClient("k", sdk_client=FakeOpenAI(r2)).complete([{"role": "user", "content": "x"}], system=None,
                                                                  role=role())

    def test_pdf_and_image_attachments(self):
        pdf = self.tmp / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4 x")
        png = self.tmp / "f.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        content = [{"type": "text", "text": "review"},
                   {"type": "file", "path": str(pdf), "name": "p.pdf", "kind": "pdf"},
                   {"type": "file", "path": str(png), "name": "f.png", "kind": "image"}]
        r = FakeResponses()
        OpenAIClient("k", sdk_client=FakeOpenAI(r)).complete([{"role": "user", "content": content}], system=None,
                                                             role=role())
        parts = r.created[0]["input"][0]["content"]
        kinds = [p["type"] for p in parts]
        self.assertEqual(kinds, ["input_text", "input_file", "input_text", "input_image"])
        self.assertTrue(parts[1]["file_data"].startswith("data:application/pdf;base64,"))


# ---------------------------------------------------------------------------------------------- fake Anthropic
def amsg(text="hi", stop="end_turn", category=None):
    return NS(content=[NS(type="thinking", thinking=""), NS(type="text", text=text)], stop_reason=stop,
              stop_details=NS(category=category) if stop == "refusal" else None, model="claude-test",
              id="msg_1", usage=NS(model_dump=lambda: {"output_tokens": 5}))


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter([NS(type="message_start"), NS(type="message_stop")])

    def get_final_message(self):
        return self.msg


class FakeMessages:
    def __init__(self, replies, reject_fallbacks_kw=False):
        self.replies = list(replies)
        self.calls = []
        self.reject = reject_fallbacks_kw

    def stream(self, **params):
        if self.reject and "fallbacks" in params:
            raise TypeError("stream() got an unexpected keyword argument 'fallbacks'")
        self.calls.append(params)
        return FakeStream(self.replies.pop(0))


class FakeAnthropic:
    def __init__(self, replies, reject=False):
        self.messages = FakeMessages(replies)
        self.beta = NS(messages=FakeMessages(replies, reject_fallbacks_kw=reject))

    def with_options(self, **kw):
        return self


def crole(**kw):
    base = dict(provider="anthropic", model="claude-opus-5-5", effort="high", max_attempts=1, backoff_s=[0.0])
    base.update(kw)
    return RoleCfg(**base)


class Anthropic(TempDirMixin, unittest.TestCase):
    def test_fallbacks_thinking_effort_cache_and_tools(self):
        fake = FakeAnthropic([amsg()])
        rep = AnthropicClient("k", sdk_client=fake).complete([{"role": "user", "content": "x"}], system="s",
                                                             role=crole(web_search=True))
        p = fake.beta.messages.calls[0]
        self.assertEqual(p["betas"], [FALLBACK_BETA])
        self.assertEqual(p["fallbacks"], "default")
        self.assertEqual(p["thinking"], {"type": "adaptive"})
        self.assertEqual(p["output_config"], {"effort": "high"})
        self.assertEqual(p["cache_control"], {"type": "ephemeral"})
        self.assertEqual(p["tools"][0]["type"], "web_search_20260209")
        self.assertEqual(p["max_tokens"], 64000)
        self.assertEqual(rep.text, "hi")

    def test_older_sdk_gets_fallbacks_in_extra_body(self):
        fake = FakeAnthropic([amsg()], reject=True)
        AnthropicClient("k", sdk_client=fake).complete([{"role": "user", "content": "x"}], system=None,
                                                       role=crole())
        p = fake.beta.messages.calls[0]
        self.assertNotIn("fallbacks", p)
        self.assertEqual(p["extra_body"], {"fallbacks": "default"})

    def test_models_without_fallbacks_use_the_regular_endpoint(self):
        fake = FakeAnthropic([amsg()])
        AnthropicClient("k", sdk_client=fake).complete([{"role": "user", "content": "x"}], system=None,
                                                       role=crole(model="claude-haiku-5-5"))
        self.assertEqual(len(fake.messages.calls), 1)
        self.assertEqual(fake.beta.messages.calls, [])

    def test_refusal_and_truncation(self):
        fake = FakeAnthropic([amsg(stop="refusal", category="cyber")])
        with self.assertRaises(LLMRefusal) as cm:
            AnthropicClient("k", sdk_client=fake).complete([{"role": "user", "content": "x"}], system=None,
                                                           role=crole())
        self.assertEqual(cm.exception.category, "cyber")
        fake2 = FakeAnthropic([amsg(stop="max_tokens")])
        self.assertTrue(AnthropicClient("k", sdk_client=fake2).complete(
            [{"role": "user", "content": "x"}], system=None, role=crole()).truncated)

    def test_paused_turn_is_continued(self):
        fake = FakeAnthropic([amsg("part one. ", stop="pause_turn"), amsg("part two.")])
        rep = AnthropicClient("k", sdk_client=fake).complete([{"role": "user", "content": "x"}], system=None,
                                                             role=crole())
        self.assertEqual(rep.text, "part one. part two.")
        second = fake.beta.messages.calls[1]["messages"]
        self.assertEqual(second[-1]["role"], "assistant")

    def test_documents_go_before_text(self):
        pdf = self.tmp / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4 x")
        fake = FakeAnthropic([amsg()])
        content = [{"type": "text", "text": "review"}, {"type": "file", "path": str(pdf), "name": "p.pdf",
                                                         "kind": "pdf"}]
        AnthropicClient("k", sdk_client=fake).complete([{"role": "user", "content": content}], system=None,
                                                       role=crole())
        blocks = fake.beta.messages.calls[0]["messages"][0]["content"]
        self.assertEqual([b["type"] for b in blocks], ["document", "text"])


if __name__ == "__main__":
    unittest.main()
