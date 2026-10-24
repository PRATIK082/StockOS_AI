"""LM Studio and llama.cpp providers.

Both are thin subclasses of the OpenAI-compatible provider; they only differ by
their default endpoint.
"""

from __future__ import annotations

from app.services.llm.providers.openai_compat import OpenAICompatProvider


class LMStudioProvider(OpenAICompatProvider):
    name = "lmstudio"


class LlamacppProvider(OpenAICompatProvider):
    name = "llamacpp"
