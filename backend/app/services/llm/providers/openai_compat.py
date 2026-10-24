"""Generic OpenAI-compatible chat provider (httpx based).

Works with any server exposing the OpenAI `/chat/completions` API — LM Studio,
llama.cpp, vLLM, and cloud providers (OpenAI, DeepSeek, Together, ...).
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from app.core.logging import get_logger
from app.services.llm.providers.base import ChatMessage, LLMProvider

logger = get_logger("llm.openai_compat")


class OpenAICompatProvider(LLMProvider):
    name = "openai"

    def __init__(self, base_url: str, api_key: str = "", default_model: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._as_dicts(messages),
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._as_dicts(messages),
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    for chunk in self._sse_chunks(line.encode()):
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers)
                resp.raise_for_status()
                data = resp.json()
                ids = [m.get("id") for m in data.get("data", [])]
                return [str(i) for i in ids if i]
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_models failed for %s: %s", self.base_url, exc)
            return [self.default_model] if self.default_model else []
