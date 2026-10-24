"""LLM Gateway.

Registry of configured providers. Resolves a requested provider/model and
dispatches non-streaming or streaming chat calls. Local providers are
auto-detected on first use (e.g. which Ollama models are pulled).
"""

from __future__ import annotations

from typing import AsyncIterator

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm.providers import (
    ChatMessage,
    LMStudioProvider,
    LLMProvider,
    LlamacppProvider,
    OllamaProvider,
    OpenAICompatProvider,
)

logger = get_logger("llm.gateway")

SUPPORTED_PROVIDERS = {"ollama", "lmstudio", "llamacpp", "openai"}


def build_provider(name: str) -> LLMProvider:
    name = (name or "").lower()
    if name not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider '{name}'. Supported: {sorted(SUPPORTED_PROVIDERS)}"
        )

    if name == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.llm_default_model)
    if name == "lmstudio":
        return LMStudioProvider(
            settings.lmstudio_base_url, default_model=settings.llm_default_model
        )
    if name == "llamacpp":
        return LlamacppProvider(
            settings.llamacpp_base_url, default_model=settings.llm_default_model
        )
    return OpenAICompatProvider(
        settings.openai_base_url,
        api_key=settings.openai_api_key,
        default_model=settings.openai_model,
    )


class LLMGateway:
    """Thin facade over the provider registry."""

    def __init__(self) -> None:
        self._cache: dict[str, LLMProvider] = {}

    def provider(self, name: str | None = None) -> LLMProvider:
        name = name or settings.llm_default_provider
        if name not in self._cache:
            self._cache[name] = build_provider(name)
        return self._cache[name]

    async def resolve_model(self, provider_name: str | None = None, model: str | None = None) -> str:
        """Return a concrete model id, auto-detecting local models if unset."""
        if model:
            return model
        prov = self.provider(provider_name)
        if prov.default_model:
            return prov.default_model
        models = await prov.list_models()
        if not models:
            raise RuntimeError(
                f"No model available on provider '{provider_name}'. "
                f"Start Ollama/LM Studio/llama.cpp or set LLM_DEFAULT_MODEL."
            )
        chosen = models[0]
        logger.info("Auto-detected model '%s' on provider '%s'", chosen, provider_name)
        return chosen

    async def chat(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> str:
        norm = [m if isinstance(m, ChatMessage) else ChatMessage(**m) for m in messages]
        resolved = await self.resolve_model(provider, model)
        return await self.provider(provider).chat(
            norm, model=resolved, temperature=temperature, max_tokens=max_tokens
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        norm = [m if isinstance(m, ChatMessage) else ChatMessage(**m) for m in messages]
        resolved = await self.resolve_model(provider, model)
        async for chunk in self.provider(provider).stream_chat(
            norm, model=resolved, temperature=temperature, max_tokens=max_tokens
        ):
            yield chunk

    async def list_models(self, provider: str | None = None) -> list[str]:
        return await self.provider(provider).list_models()


gateway = LLMGateway()
