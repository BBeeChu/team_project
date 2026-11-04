"""Model clients. `get_client(cfg, role_name)` returns the client that serves a role (OpenAI, Anthropic or the mock)."""
from __future__ import annotations

from ..config import Config, ConfigError
from .base import LLMClient, LLMError, LLMRefusal, LLMReply, TransientLLMError

_CACHE: dict[tuple, object] = {}


def get_client(cfg: Config, role_name: str) -> LLMClient:
    role = cfg.role(role_name)
    if role.provider == "mock":
        from .mock_client import MockClient
        key = ("mock", cfg.mock.scenario, cfg.chain.manuscript)
        if key not in _CACHE:
            _CACHE[key] = MockClient(cfg.mock.scenario, markdown=cfg.chain.manuscript == "markdown")
        return _CACHE[key]  # type: ignore[return-value]
    if role.provider == "openai":
        api_key = cfg.keys.openai()
        if not api_key:
            raise ConfigError("no OpenAI API key: set OPENAI_API_KEY or keys.openai_api_key in config.toml")
        key = ("openai", api_key)
        if key not in _CACHE:
            from .openai_client import OpenAIClient
            _CACHE[key] = OpenAIClient(api_key)
        return _CACHE[key]  # type: ignore[return-value]
    if role.provider == "anthropic":
        api_key = cfg.keys.anthropic()
        if not api_key:
            raise ConfigError("no Anthropic API key: set ANTHROPIC_API_KEY or keys.anthropic_api_key in config.toml")
        key = ("anthropic", api_key)
        if key not in _CACHE:
            from .anthropic_client import AnthropicClient
            _CACHE[key] = AnthropicClient(api_key)
        return _CACHE[key]  # type: ignore[return-value]
    raise ConfigError(f"roles.{role_name}.provider: unknown provider {role.provider!r}")


def reset_clients() -> None:
    _CACHE.clear()


__all__ = ["get_client", "reset_clients", "LLMClient", "LLMError", "LLMRefusal", "LLMReply", "TransientLLMError"]
