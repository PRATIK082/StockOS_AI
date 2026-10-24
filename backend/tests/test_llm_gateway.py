"""Tests for the LLM gateway and provider resolution."""

from __future__ import annotations

import pytest

from app.services.llm.gateway import build_provider
from app.services.llm.providers import ChatMessage


def test_build_provider_all_supported() -> None:
    for name in ("ollama", "lmstudio", "llamacpp", "openai"):
        assert build_provider(name).name == name


def test_build_provider_unknown_raises() -> None:
    with pytest.raises(ValueError):
        build_provider("nonexistent")


def test_chat_message_model_dump() -> None:
    msg = ChatMessage(role="user", content="hello")
    assert msg.model_dump() == {"role": "user", "content": "hello"}


def test_sse_chunk_parsing() -> None:
    prov = build_provider("ollama")
    chunks = prov._sse_chunks(b'data: {"choices":[{"delta":{"content":"hi"}}]}')
    assert chunks and chunks[0]["choices"][0]["delta"]["content"] == "hi"
    assert prov._sse_chunks(b"data: [DONE]") == []
