"""Per-user LLM provider selection for the Trading Desk engine.

The vendored TradingAgents engine supports many providers (OpenAI, Anthropic,
Gemini, DeepSeek, OpenRouter, Azure, local Ollama, and any OpenAI-compatible
endpoint). StockOS defaults to the local Ollama runtime but lets each user run
the engine against their own provider + API key, passed per-run **without
mutating process environment variables** (the vendored clients forward an
``api_key`` kwarg through ``_PASSTHROUGH_KWARGS``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

# ---------------------------------------------------------------------------
# Provider registry (id -> metadata)
# ---------------------------------------------------------------------------

ProviderMeta = dict[str, Any]


def _providers() -> dict[str, ProviderMeta]:
    return {
        "openai": {
            "label": "OpenAI (GPT)",
            "needs_key": True,
            "needs_base_url": False,
            "key_env": "OPENAI_API_KEY",
            "default_deep": "gpt-5.5",
            "default_quick": "gpt-5.4-mini",
            "hint": "OpenAI platform API key (sk-...).",
        },
        "anthropic": {
            "label": "Anthropic Claude",
            "needs_key": True,
            "needs_base_url": False,
            "key_env": "ANTHROPIC_API_KEY",
            "default_deep": "claude-sonnet-4-6",
            "default_quick": "claude-sonnet-4-6",
            "hint": "Anthropic Console API key (sk-ant-...).",
        },
        "google": {
            "label": "Google Gemini",
            "needs_key": True,
            "needs_base_url": False,
            "key_env": "GOOGLE_API_KEY",
            "default_deep": "gemini-3-pro",
            "default_quick": "gemini-3-flash",
            "hint": "Google AI Studio / Vertex API key (AIza...).",
        },
        "deepseek": {
            "label": "DeepSeek",
            "needs_key": True,
            "needs_base_url": False,
            "key_env": "DEEPSEEK_API_KEY",
            "default_deep": "deepseek-v4-pro",
            "default_quick": "deepseek-v4-flash",
            "hint": "DeepSeek API key (sk-...).",
        },
        "openrouter": {
            "label": "OpenRouter",
            "needs_key": True,
            "needs_base_url": False,
            "key_env": "OPENROUTER_API_KEY",
            "default_deep": "openai/gpt-5.5",
            "default_quick": "openai/gpt-5.4-mini",
            "hint": "OpenRouter API key; model = any OpenRouter model id.",
        },
        "azure": {
            "label": "Azure OpenAI",
            "needs_key": True,
            "needs_base_url": True,
            "key_env": "AZURE_OPENAI_API_KEY",
            "default_deep": "",
            "default_quick": "",
            "hint": "Azure endpoint https://<res>.openai.azure.com/ + key + deployment model.",
        },
        "ollama": {
            "label": "Ollama (local)",
            "needs_key": False,
            "needs_base_url": False,
            "key_env": None,
            "default_deep": "",
            "default_quick": "",
            "is_local": True,
            "hint": "Local models already pulled on the machine.",
        },
        "openai_compatible": {
            "label": "OpenAI-compatible (LM Studio / vLLM / Groq...)",
            "needs_key": False,
            "needs_base_url": True,
            "key_env": "OPENAI_COMPATIBLE_API_KEY",
            "default_deep": "",
            "default_quick": "",
            "hint": "Any /v1 endpoint: LM Studio, vLLM, llama.cpp, Groq.",
        },
    }


PROVIDERS: dict[str, ProviderMeta] = _providers()

# Engine provider-name aliases accepted by the vendored client factory.
ENGINE_PROVIDER_NAMES: set[str] = set(PROVIDERS)


@dataclass
class LLMSelection:
    """One user's per-run choice of engine LLM."""

    provider: str = "ollama"
    deep_model: str | None = None
    quick_model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    llm_max_retries: int | None = None


def provider_needs_key(provider: str) -> bool:
    meta = PROVIDERS.get(provider)
    return bool(meta and meta.get("needs_key"))


def provider_needs_base_url(provider: str) -> bool:
    meta = PROVIDERS.get(provider)
    return bool(meta and meta.get("needs_base_url"))


def validate_selection(sel: LLMSelection) -> list[str]:
    """Return human-readable validation errors for a selection (empty = ok)."""
    errors: list[str] = []
    if sel.provider not in PROVIDERS:
        errors.append(f"Unknown provider '{sel.provider}'. Available: {sorted(PROVIDERS)}")
        return errors
    meta = PROVIDERS[sel.provider]
    if meta.get("needs_key") and not sel.api_key:
        errors.append(
            f"Provider '{sel.provider}' requires an API key "
            f"(set {meta.get('key_env')} globally or provide one per run)."
        )
    if meta.get("needs_base_url") and not sel.base_url:
        errors.append(
            f"Provider '{sel.provider}' requires a base_url/base endpoint."
        )
    if sel.provider == "azure" and not sel.deep_model:
        errors.append("Azure requires a deployment model name (deep_model).")
    return errors


def public_provider_list() -> list[dict[str, Any]]:
    """Provider metadata for the Trading Desk UI (no secrets)."""
    out = []
    for pid, meta in PROVIDERS.items():
        out.append(
            {
                "provider": pid,
                "label": meta.get("label"),
                "is_local": bool(meta.get("is_local")),
                "needs_key": bool(meta.get("needs_key")),
                "needs_base_url": bool(meta.get("needs_base_url")),
                "key_env": meta.get("key_env"),
                "default_deep": meta.get("default_deep", ""),
                "default_quick": meta.get("default_quick", ""),
                "hint": meta.get("hint", ""),
            }
        )
    return out


async def resolve_models(sel: LLMSelection) -> tuple[str, str]:
    """Return (deep_model, quick_model) for a selection.

    Precedence: explicit selection model > provider default > (Ollama) the
    actually-pulled local model (auto-detected via the StockOS LLM gateway).
    """
    meta = PROVIDERS.get(sel.provider, {})
    default_deep = meta.get("default_deep") or ""
    default_quick = meta.get("default_quick") or ""

    if sel.deep_model:
        deep = sel.deep_model
    elif default_deep:
        deep = default_deep
    else:
        deep = ""

    if sel.quick_model:
        quick = sel.quick_model
    elif default_quick:
        quick = default_quick
    else:
        quick = ""

    if sel.provider == "ollama" and (not deep or not quick):
        local = await _pick_ollama_model()
        if not deep:
            deep = local
        if not quick:
            quick = local

    if not deep or not quick:
        raise ValueError(
            f"Provider '{sel.provider}' needs explicit deep/quick model ids."
        )
    return deep, quick


async def _pick_ollama_model() -> str:
    """Prefer a capable reasoning model actually pulled in Ollama."""
    from app.services.llm.gateway import gateway

    try:
        models = await gateway.list_models("ollama")
    except Exception:
        models = []
    if not models:
        if settings.llm_default_model:
            return settings.llm_default_model
        raise ValueError(
            "Ollama is not reachable and no default model is configured. "
            "Start Ollama and pull a model, or choose another provider."
        )
    # Prefer larger / thinking models; fall back to first available.
    order = ["qwen3:14b", "ministral-3:14b", "qwen3-vl:8b"]
    for preferred in order:
        if preferred in models:
            return preferred
    return models[0]