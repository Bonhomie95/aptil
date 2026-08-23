"""Provider-agnostic LLM router (spec point 18).

Wraps LiteLLM so the rest of the app never hard-codes a provider. Supports:
- Multiple API keys per provider (round-robin rotation across a key pool).
- Automatic failover: default model -> fallback models on error.
- Local Ollama as a first-class provider for a future self-trained model.

Model strings are LiteLLM-style: "anthropic/claude-sonnet-5", "openai/gpt-4o-mini",
"xai/grok-2", "groq/llama-3.3-70b-versatile", "ollama/llama3.1".
"""

from __future__ import annotations

import itertools
import json
import re
import threading
from typing import Any

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

litellm.drop_params = True  # ignore params a given provider doesn't support


def _redact(message: str) -> str:
    """Strip anything that looks like an API key out of an error string.

    Provider SDKs happily echo the key back in exception text; those strings end
    up in logs.
    """
    text = str(message)
    for pattern in (
        r"sk-[A-Za-z0-9_\-]{8,}",
        r"xai-[A-Za-z0-9_\-]{8,}",
        r"gsk_[A-Za-z0-9_\-]{8,}",
        r"Bearer\s+[A-Za-z0-9._\-]{8,}",
    ):
        text = re.sub(pattern, "[redacted]", text)
    for key in _ALL_KEYS:
        if key and key in text:
            text = text.replace(key, "[redacted]")
    return text[:500]


class _KeyPools:
    """Round-robin key pools per provider prefix. Safe under concurrency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cycles: dict[str, itertools.cycle] = {}
        self._register("openai", settings.key_pool(settings.OPENAI_API_KEYS))
        self._register("anthropic", settings.key_pool(settings.ANTHROPIC_API_KEYS))
        self._register("xai", settings.key_pool(settings.XAI_API_KEYS))
        self._register("groq", settings.key_pool(settings.GROQ_API_KEYS))

    def _register(self, provider: str, keys: list[str]) -> None:
        if keys:
            self._cycles[provider] = itertools.cycle(keys)

    def has_provider(self, provider: str) -> bool:
        return provider in self._cycles

    def next_key(self, model: str) -> str | None:
        provider = model.split("/", 1)[0]
        # itertools.cycle is not thread-safe and these are shared across the
        # thread pool the API uses to run completions off the event loop.
        with self._lock:
            cycle = self._cycles.get(provider)
            return next(cycle) if cycle else None


_ALL_KEYS: list[str] = [
    k
    for raw in (
        settings.OPENAI_API_KEYS,
        settings.ANTHROPIC_API_KEYS,
        settings.XAI_API_KEYS,
        settings.GROQ_API_KEYS,
    )
    for k in settings.key_pool(raw)
]

_pools = _KeyPools()


def has_any_provider() -> bool:
    """True when a hosted provider key is configured.

    Deliberately does NOT count Ollama: OLLAMA_BASE_URL ships with a default, so
    including it made this return True on every install and the answer carried
    no information. Ollama only runs behind a compose profile, so its URL
    resolving is not evidence anything is listening on it.
    """
    return bool(_ALL_KEYS)


def _models_to_try(model: str | None) -> list[str]:
    primary = model or settings.LLM_DEFAULT_MODEL
    fallbacks = settings.key_pool(settings.LLM_FALLBACK_MODELS)
    ordered = [primary, *[m for m in fallbacks if m != primary]]
    # Drop hosted models we have no key for: trying them only burns time before
    # the real fallback, and the error text is noise.
    usable = [
        m
        for m in ordered
        if m.startswith("ollama/") or _pools.has_provider(m.split("/", 1)[0])
    ]
    return usable or ordered


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=8))
def _complete_one(model: str, messages: list[dict[str, Any]], **kwargs) -> str:
    call_kwargs: dict[str, Any] = dict(kwargs)
    api_key = _pools.next_key(model)
    if api_key:
        call_kwargs["api_key"] = api_key
    if model.startswith("ollama/"):
        call_kwargs["api_base"] = settings.OLLAMA_BASE_URL

    response = litellm.completion(
        model=model, messages=messages, timeout=90, **call_kwargs
    )
    content = response["choices"][0]["message"]["content"]
    if not content:
        raise RuntimeError("Model returned an empty response")
    return content


def chat(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    **extra: Any,
) -> str:
    """Chat completion with automatic model failover."""
    last_error: Exception | None = None
    for candidate in _models_to_try(model):
        try:
            return _complete_one(
                candidate,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )
        except Exception as exc:  # noqa: BLE001 - try the next model
            last_error = exc
            log.warning("llm_model_failed", model=candidate, error=_redact(exc))
    raise RuntimeError(f"All LLM models failed: {_redact(last_error)}")


def chat_json(
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Chat completion constrained to JSON output. Returns a parsed dict."""
    content = chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        # LiteLLM passes this through to providers that support JSON mode.
        response_format={"type": "json_object"},
    )
    content = (content or "").strip()
    # Models sometimes wrap JSON in a markdown fence despite json mode.
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Best-effort recovery: extract the first {...} block.
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(content[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model returned JSON that is not an object")
    return parsed
