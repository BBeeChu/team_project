"""OpenAI models through the Responses API.

Long reasoning replies (a high-effort reply can run for an hour) use background
mode: the request is created with background=True, its id is saved at once (on_started), and the client polls
responses.retrieve until the status leaves queued/in_progress. A restarted pipeline resumes polling the same id.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from ..attachments import to_openai_content
from ..config import RoleCfg
from ..util import LOG
from .base import (LLMCancelled, LLMError, LLMRefusal, LLMReply, StartedHook, TransientLLMError,
                   call_with_retries)

ACTIVE = {"queued", "in_progress"}


class OpenAIClient:
    provider = "openai"

    def __init__(self, api_key: str, sdk_client: Any = None):
        if sdk_client is None:
            try:
                import openai  # imported lazily so the mock pipeline and the tests run without the SDK
            except ImportError as e:  # pragma: no cover - depends on the environment
                raise LLMError("the 'openai' package is not installed: pip install -r requirements.txt") from e
            sdk_client = openai.OpenAI(api_key=api_key, max_retries=2)
        self._client = sdk_client

    # ------------------------------------------------------------------ public
    def complete(self, messages: list[dict], *, system: str | None, role: RoleCfg, stage: str = "",
                 on_started: StartedHook | None = None, resume_id: str | None = None,
                 cancel: threading.Event | None = None) -> LLMReply:
        what = f"openai:{role.model}:{stage or 'call'}"
        pending = {"resume": resume_id}      # only the first attempt resumes; a retry sends a new request

        def once() -> LLMReply:
            t0 = time.monotonic()
            rid = pending.pop("resume", None)
            try:
                if rid:
                    resp = self._poll(rid, role, what, t0, cancel)
                else:
                    resp = self._create(messages, system, role, on_started, what, t0, cancel)
                return self._to_reply(resp, role, time.monotonic() - t0)
            except (LLMRefusal, LLMCancelled, TransientLLMError):
                raise
            except LLMError as e:
                if rid:   # the saved request is gone or was cancelled: send a new one
                    raise TransientLLMError(f"resumed response {rid} is unusable ({e})") from e
                raise

        return call_with_retries(once, role, what)

    # ----------------------------------------------------------------- helpers
    def _create(self, messages, system, role: RoleCfg, on_started, what, t0, cancel=None):
        kwargs: dict[str, Any] = {
            "model": role.model,
            "input": [{"role": m["role"], "content": to_openai_content(m["content"], m["role"])} for m in messages],
        }
        if system:
            kwargs["instructions"] = system
        if role.effort:
            kwargs["reasoning"] = {"effort": role.effort}
        if role.max_output_tokens and role.max_output_tokens > 0:
            kwargs["max_output_tokens"] = role.max_output_tokens
        if role.web_search:
            kwargs["tools"] = [{"type": role.web_search_type or "web_search"}]
        try:
            if role.background:
                # extra_body keeps this working on SDK versions whose typed signature predates background mode
                resp = self._client.with_options(timeout=120).responses.create(
                    **kwargs, store=True, extra_body={"background": True})
                rid = getattr(resp, "id", "") or ""
                if rid and on_started:
                    on_started(rid)
                LOG.info("%s: background response %s (%s)", what, rid, getattr(resp, "status", "?"))
                if getattr(resp, "status", "") in ACTIVE:
                    resp = self._poll(rid, role, what, t0, cancel)
                return resp
            return self._client.with_options(timeout=role.timeout_s).responses.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - mapped to our error classes
            raise _map_error(e) from e

    def _poll(self, response_id: str, role: RoleCfg, what: str, t0: float, cancel=None):
        deadline = t0 + role.timeout_s
        resp = None
        while True:
            if cancel is not None and cancel.is_set():
                try:
                    self._client.responses.cancel(response_id)
                except Exception:  # noqa: BLE001 - best effort
                    pass
                raise LLMCancelled(f"{what}: cancelled by the pipeline (response {response_id})")
            try:
                resp = self._client.responses.retrieve(response_id)
            except Exception as e:  # noqa: BLE001
                err = _map_error(e)
                if not isinstance(err, TransientLLMError):
                    raise err from e
                LOG.warning("%s: polling %s failed (%s); polling again", what, response_id, e)
            else:
                status = getattr(resp, "status", "")
                if status not in ACTIVE:
                    return resp
            if time.monotonic() > deadline:
                try:
                    self._client.responses.cancel(response_id)
                except Exception:  # noqa: BLE001 - best effort
                    pass
                raise LLMError(f"{what}: no reply after {role.timeout_s:.0f} s (response {response_id} cancelled)")
            time.sleep(max(1.0, role.poll_s))

    def _to_reply(self, resp, role: RoleCfg, elapsed: float) -> LLMReply:
        status = getattr(resp, "status", "completed") or "completed"
        text = _output_text(resp)
        truncated = False
        if status == "incomplete":
            reason = getattr(getattr(resp, "incomplete_details", None), "reason", "") or ""
            if reason == "content_filter":
                raise LLMRefusal(f"openai:{role.model}: reply stopped by the content filter", category=reason)
            truncated = True
            LOG.warning("openai:%s: reply incomplete (%s); keeping %d characters", role.model, reason, len(text))
        elif status == "failed":
            err = getattr(resp, "error", None)
            code = getattr(err, "code", "") or ""
            msg = getattr(err, "message", "") or str(err)
            cls = TransientLLMError if code in ("rate_limit_exceeded", "server_error") else LLMError
            raise cls(f"openai:{role.model}: response failed ({code}): {msg}")
        elif status == "cancelled":
            raise LLMError(f"openai:{role.model}: response was cancelled")
        if not text.strip() and not truncated:
            raise TransientLLMError(f"openai:{role.model}: empty reply")
        usage = {}
        u = getattr(resp, "usage", None)
        if u is not None:
            usage = u.model_dump() if hasattr(u, "model_dump") else dict(u)
        return LLMReply(text=text, provider="openai", model=getattr(resp, "model", role.model) or role.model,
                        stop_reason=status, response_id=getattr(resp, "id", "") or "", usage=usage,
                        elapsed_s=elapsed, truncated=truncated)


def _output_text(resp) -> str:
    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text:
        return text
    parts: list[str] = []
    for item in getattr(resp, "output", None) or []:
        if getattr(item, "type", "") != "message":
            continue
        for c in getattr(item, "content", None) or []:
            if getattr(c, "type", "") == "output_text":
                parts.append(getattr(c, "text", ""))
    return "".join(parts)


def _map_error(e: Exception) -> LLMError:
    """Map SDK exceptions (by class name, so the SDK stays optional) to transient or permanent errors."""
    if isinstance(e, LLMError):
        return e
    names = {c.__name__ for c in type(e).__mro__}
    status = getattr(e, "status_code", None)
    if names & {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"}:
        return TransientLLMError(str(e))
    if status is not None and (status in (408, 409, 429) or status >= 500):
        return TransientLLMError(str(e))
    if isinstance(e, (TimeoutError, ConnectionError)):
        return TransientLLMError(str(e))
    return LLMError(f"{type(e).__name__}: {e}")
