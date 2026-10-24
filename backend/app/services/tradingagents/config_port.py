"""Build the per-run engine config for the vendored TradingAgents graph.

The TradingDesk engine turns a user's ``LLMSelection`` (provider + models +
per-user API key) plus the global StockOS ``ta_*`` settings into the config
dict that ``TradingAgentsGraph`` consumes. The API key is passed **inside the
config** (``config["api_key"]``) and the StockOS graph subclass forwards it to
the provider clients via LLM kwargs — never through process environment
variables, so concurrent users can each use their own provider and key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.tradingagents.llm_port import LLMSelection, resolve_models


def _data_dir() -> Path:
    return Path(settings.ta_data_root).expanduser()


async def build_engine_config(
    sel: LLMSelection,
    *,
    max_debate_rounds: int | None = None,
    max_risk_rounds: int | None = None,
    checkpoint_enabled: bool = False,
    output_language: str = "English",
) -> dict[str, Any]:
    """Build the vendored engine config for one run.

    Precedence for scalar knobs: explicit arg > ``ta_*`` setting > vendored
    default. ``sel`` decides provider, models (resolved/auto-detected), API
    key and base URL.

    Returns a fresh dict every call; the caller passes it straight into the
    graph constructor. Never mutates the environment or the vendored default.
    """
    deep_model, quick_model = await resolve_models(sel)

    data_root = _data_dir()
    cache_dir = data_root / "cache"
    results_dir = data_root / "results"
    memory_dir = data_root / "memory"

    config: dict[str, Any] = {
        # LLM selection
        "llm_provider": sel.provider,
        "deep_think_llm": deep_model,
        "quick_think_llm": quick_model,
        "backend_url": sel.base_url,
        # StockOS-only extra key read by StockTradingAgentsGraph._get_provider_kwargs.
        "api_key": sel.api_key,
        # Engine behaviour
        "output_language": output_language,
        "max_debate_rounds": max_debate_rounds
        if max_debate_rounds is not None
        else settings.ta_max_debate_rounds,
        "max_risk_discuss_rounds": max_risk_rounds
        if max_risk_rounds is not None
        else settings.ta_max_risk_rounds,
        "max_recur_limit": settings.ta_max_recur_limit,
        "news_article_limit": settings.ta_news_article_limit,
        "global_news_article_limit": settings.ta_global_news_limit,
        "global_news_lookback_days": settings.ta_global_news_lookback_days,
        "benchmark_ticker": settings.ta_benchmark_ticker or None,
        "temperature": sel.temperature,
        "llm_max_retries": sel.llm_max_retries,
        "checkpoint_enabled": checkpoint_enabled,
        # Local persistence (all under the StockOS data root)
        "results_dir": str(results_dir),
        "data_cache_dir": str(cache_dir),
        "memory_log_path": str(memory_dir / "trading_memory.md"),
        "memory_log_max_entries": None,
    }

    # Only send a temperature/retry value when the caller actually picked one;
    # None keeps the provider defaults (the vendored config expects None).
    if sel.temperature is None:
        config.pop("temperature", None)
    if sel.llm_max_retries is None:
        config.pop("llm_max_retries", None)

    return config