"""LiteLLM-backed LLM provider (P5-a).

Routes chat completions through the ``litellm`` package so a single provider
id can reach local (Ollama) and OpenAI-compatible backends with per-call
``api_base`` / ``api_key`` overrides.

The ``litellm`` import is lazy (inside each method) so the rest of StockOS
imports and runs with the package absent; calls then raise a clean
``RuntimeError`` instead of ``ModuleNotFoundError``.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from app.core.logging import get_logger
from app.services.llm.providers.base import ChatMessage, LLMProvider

logger = get_logger("llm.litellm")


def litellm_model_id(model: str, api_base: str = "") -> str:
    """Map a StockOS model name to a LiteLLM model id.

    Ids that already carry a provider prefix (``ollama/...``, ``openai/...``)
    pass through untouched. Bare names against an Ollama-looking base URL get
    the ``ollama/`` prefix LiteLLM requires; anything else is passed through
    for LiteLLM's own provider resolution.
    """
    model = (model or "").strip()
    base = (api_base or "").lower()
    if not model or "/" in model:
        return model
    if "11434" in base or "ollama" in base:
        return f"ollama/{model}"
    return model


def _require_litellm() -> Any:
    try:
        import litellm
    except ImportError as exc:
        raise RuntimeError(
            "The 'litellm' package is not installed. Install it with "
            "`pip install litellm` (and `pip install mcp`, which litellm "
            "1.106+ imports) or pick another LLM provider."
        ) from exc
    return litellm


class LiteLLMProvider(LLMProvider):
    """Chat provider delegating to ``litellm.acompletion``."""

    name = "litellm"

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        default_model: str = "",
    ) -> None:
        self.api_base = (api_base or "").rstrip("/")
        self.api_key = api_key or ""
        self.default_model = default_model or ""

    def _call_kwargs(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": litellm_model_id(model or self.default_model, self.api_base),
            "messages": self._as_dicts(messages),
            "temperature": temperature,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return kwargs

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        litellm = _require_litellm()
        resp = await litellm.acompletion(
            **self._call_kwargs(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return ""
        return getattr(choices[0].message, "content", None) or ""

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        litellm = _require_litellm()
        stream = await litellm.acompletion(
            **self._call_kwargs(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            stream=True,
        )
        async for chunk in stream:
            for choice in getattr(chunk, "choices", None) or []:
                content = getattr(choice.delta, "content", None)
                if content:
                    yield content

    async def list_models(self) -> list[str]:
        base = self.api_base.lower()
        if "11434" in base or "ollama" in base:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"{self.api_base}/api/tags")
                    resp.raise_for_status()
                    models = [
                        m["name"] for m in resp.json().get("models", [])
                    ]
                    return list(dict.fromkeys(models))
            except Exception as exc:  # noqa: BLE001
                logger.warning("LiteLLM provider model listing failed: %s", exc)
        return [self.default_model] if self.default_model else []
