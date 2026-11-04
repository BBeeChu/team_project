"""Provider-neutral interface for one model call: a list of user/assistant turns in, one reply out."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..config import RoleCfg
from ..util import LOG


@dataclass
class LLMReply:
    text: str
    provider: str
    model: str
    stop_reason: str = ""
    response_id: str = ""
    usage: dict = field(default_factory=dict)
    elapsed_s: float = 0.0
    truncated: bool = False            # the reply hit the output-token limit


class LLMError(RuntimeError):
    """A call that failed for good (after retries)."""


class TransientLLMError(LLMError):
    """Rate limit, server error, dropped connection or timeout: worth retrying later."""


class LLMRefusal(LLMError):
    """The model declined the request (Anthropic stop_reason 'refusal' after any fallback)."""

    def __init__(self, message: str, category: str | None = None):
        super().__init__(message)
        self.category = category


class LLMCancelled(LLMError):
    """The pipeline cancelled the request (for example the proposer cut once enough proposals are in)."""


# Called with the provider's response id as soon as a long-running request exists, so a crashed pipeline can resume
# polling the same request instead of paying for it twice.
StartedHook = Callable[[str], None]


class LLMClient(Protocol):
    provider: str

    def complete(self, messages: list[dict], *, system: str | None, role: RoleCfg, stage: str = "",
                 on_started: StartedHook | None = None, resume_id: str | None = None,
                 cancel: threading.Event | None = None) -> LLMReply: ...


def call_with_retries(fn: Callable[[], LLMReply], role: RoleCfg, what: str) -> LLMReply:
    """Retry transient failures with the role's back-off schedule. The SDKs already retry short blips; this outer
    loop covers long rate-limit windows (minutes), by default with 60/120/300/600 s back-offs."""
    attempts = max(1, role.max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except LLMCancelled:
            raise
        except TransientLLMError as e:
            if attempt == attempts:
                raise LLMError(f"{what}: gave up after {attempts} attempts: {e}") from e
            delay = role.backoff_s[min(attempt - 1, len(role.backoff_s) - 1)] if role.backoff_s else 30.0
            LOG.warning("%s: transient failure (%s); retry %d/%d in %.0f s", what, e, attempt, attempts - 1, delay)
            time.sleep(delay)
    raise LLMError(f"{what}: no attempt made")  # pragma: no cover
