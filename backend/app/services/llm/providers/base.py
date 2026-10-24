"""LLM provider interface and shared types.

Every provider (Ollama, LM Studio, llama.cpp, cloud OpenAI-compatible) is
exposed through a single async interface so agents never care where a model
runs.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMProvider(ABC):
    """Abstract chat-completion provider."""

    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        """Run a non-streaming chat completion, returning the full text."""

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion, yielding text chunks."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return the model identifiers available on this provider."""

    def _as_dicts(self, messages: list[ChatMessage]) -> list[dict[str, str]]:
        return [m.model_dump() for m in messages]

    def _sse_chunks(self, line: bytes) -> list[dict[str, Any]]:
        """Parse one SSE event line into JSON payload(s)."""
        text = line.decode("utf-8", errors="ignore").strip()
        if not text.startswith("data:"):
            return []
        data = text[len("data:"):].strip()
        if data in ("", "[DONE]"):
            return []
        try:
            return [json.loads(data)]
        except json.JSONDecodeError:
            return []
