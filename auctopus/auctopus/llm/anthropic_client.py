"""Claude through the Anthropic Messages API.

Every request streams (long replies with large max_tokens would otherwise hit HTTP timeouts) and reads the final
message with get_final_message(). Thinking is adaptive and the depth is set with output_config.effort. On the models
that support it, server-side refusal fallbacks are on (fallbacks="default"): a request declined by a safety classifier
is re-run on Anthropic's recommended fallback model inside the same call. stop_reason is always checked before the
content is read.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from ..attachments import to_anthropic_content
from ..config import RoleCfg
from ..util import LOG
from .base import (LLMCancelled, LLMError, LLMRefusal, LLMReply, StartedHook, TransientLLMError,
                   call_with_retries)

# Models that accept the server-side fallback parameter (not Haiku: its declines have no server-side fallback).
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_MAX_TOKENS = 64000


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str, sdk_client: Any = None):
        if sdk_client is None:
            try:
                import anthropic  # imported lazily so the mock pipeline and the tests run without the SDK
            except ImportError as e:  # pragma: no cover - depends on the environment
                raise LLMError("the 'anthropic' package is not installed: pip install -r requirements.txt") from e
            sdk_client = anthropic.Anthropic(api_key=api_key, max_retries=2)
        self._client = sdk_client

    def complete(self, messages: list[dict], *, system: str | None, role: RoleCfg, stage: str = "",
                 on_started: StartedHook | None = None, resume_id: str | None = None,
                 cancel: threading.Event | None = None) -> LLMReply:
        what = f"anthropic:{role.model}:{stage or 'call'}"

        def once() -> LLMReply:
            t0 = time.monotonic()
            params = build_params(messages, system, role)
            use_fallbacks = role.fallbacks and role.model in FALLBACK_MODELS
            earlier_text: list[str] = []
            try:
                msg = self._stream(params, role, use_fallbacks, cancel, what)
                # A server tool (web search) can pause a long turn; send the partial turn back to let it continue.
                for _ in range(max(0, role.max_continuations)):
                    if getattr(msg, "stop_reason", "") != "pause_turn":
                        break
                    earlier_text.append(_text_of(msg))
                    params = dict(params, messages=list(params["messages"]) + [
                        {"role": "assistant", "content": msg.content}])
                    msg = self._stream(params, role, use_fallbacks, cancel, what)
            except LLMError:
                raise
            except Exception as e:  # noqa: BLE001 - mapped to our error classes
                raise _map_error(e) from e
            return self._to_reply(msg, role, time.monotonic() - t0, what, prefix="".join(earlier_text))

        return call_with_retries(once, role, what)

    def _stream(self, params: dict, role: RoleCfg, use_fallbacks: bool, cancel, what: str):
        client = self._client.with_options(timeout=role.timeout_s)
        if not use_fallbacks:
            with client.messages.stream(**params) as stream:
                return _drain(stream, cancel, what)
        beta_params = dict(params, betas=[FALLBACK_BETA], fallbacks="default")
        try:
            with client.beta.messages.stream(**beta_params) as stream:
                return _drain(stream, cancel, what)
        except TypeError as e:
            if "fallbacks" not in str(e):
                raise
            # an SDK release whose typed signature predates the parameter: send it as a raw body field
            beta_params.pop("fallbacks")
            beta_params["extra_body"] = {"fallbacks": "default"}
            with client.beta.messages.stream(**beta_params) as stream:
                return _drain(stream, cancel, what)

    def _to_reply(self, msg, role: RoleCfg, elapsed: float, what: str, prefix: str = "") -> LLMReply:
        stop = getattr(msg, "stop_reason", "") or ""
        if stop == "refusal":
            details = getattr(msg, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMRefusal(f"{what}: the model declined the request (category: {category})", category=category)
        text = prefix + _text_of(msg)
        truncated = stop == "max_tokens"
        if truncated:
            LOG.warning("%s: reply hit max_tokens (%d); keeping %d characters", what, role.max_output_tokens,
                        len(text))
        if not text.strip():
            raise TransientLLMError(f"{what}: empty reply (stop_reason {stop})")
        usage = {}
        u = getattr(msg, "usage", None)
        if u is not None:
            usage = u.model_dump() if hasattr(u, "model_dump") else dict(u)
        return LLMReply(text=text, provider="anthropic", model=getattr(msg, "model", role.model) or role.model,
                        stop_reason=stop, response_id=getattr(msg, "id", "") or "", usage=usage, elapsed_s=elapsed,
                        truncated=truncated)


def _drain(stream, cancel, what: str):
    """Consume the stream (so a cancellation can stop it between events), then return the final message."""
    if cancel is not None:
        for _event in stream:
            if cancel.is_set():
                raise LLMCancelled(f"{what}: cancelled by the pipeline")
    return stream.get_final_message()


def _text_of(msg) -> str:
    return "".join(getattr(b, "text", "") for b in (getattr(msg, "content", None) or [])
                   if getattr(b, "type", "") == "text")


def build_params(messages: list[dict], system: str | None, role: RoleCfg) -> dict:
    params: dict[str, Any] = {
        "model": role.model,
        "max_tokens": role.max_output_tokens if role.max_output_tokens and role.max_output_tokens > 0
        else DEFAULT_MAX_TOKENS,
        "messages": [{"role": m["role"], "content": to_anthropic_content(m["content"], m["role"])}
                     for m in messages],
    }
    if system:
        params["system"] = system
    if role.thinking == "adaptive":
        params["thinking"] = {"type": "adaptive"}
    if role.effort:
        params["output_config"] = {"effort": role.effort}
    if role.prompt_cache:
        params["cache_control"] = {"type": "ephemeral"}
    if role.web_search:
        params["tools"] = [{"type": role.web_search_type or "web_search_20260209", "name": "web_search"}]
    return params


def _map_error(e: Exception) -> LLMError:
    names = {c.__name__ for c in type(e).__mro__}
    status = getattr(e, "status_code", None)
    if names & {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError",
                "OverloadedError", "ServiceUnavailableError"}:
        return TransientLLMError(str(e))
    if status is not None and (status in (408, 409, 429) or status >= 500):
        return TransientLLMError(str(e))
    if isinstance(e, (TimeoutError, ConnectionError)):
        return TransientLLMError(str(e))
    return LLMError(f"{type(e).__name__}: {e}")
