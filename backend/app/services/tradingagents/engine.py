"""TradingDeskEngine — run the vendored TradingAgents pipeline on StockOS data.

Flow per run:

1. Resolve the user's ``LLMSelection`` into an engine config (provider, models,
   per-user API key, StockOS ``ta_*`` knobs) via :func:`.config_port`.
2. Build a fresh ``StockTradingAgentsGraph`` (StockOS data tools bound).
3. Stream the graph in a worker thread, surfacing step labels for the UI.
4. Derive a deterministic ``TradingSignal`` from the real decision text and
   persist a record to the local decision log.

Runs are serialised with a module-level lock because the vendored engine keeps
its configuration in a process-global (``set_config``) — safe and honest rather
than risking interleaved configs under concurrent requests.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.services.tradingagents.config_port import build_engine_config
from app.services.tradingagents.data_port import to_engine_symbol, to_stockos_symbol
from app.services.tradingagents.graph_port import (
    DEFAULT_ANALYSTS,
    StepCallback,
    StockTradingAgentsGraph,
)
from app.services.tradingagents.llm_port import LLMSelection
from app.services.tradingagents.memory import decision_log
from app.services.tradingagents.options_port import build_options_view
from app.services.tradingagents.signal import parse_trading_signal

logger = get_logger("tradingagents.engine")

_ENGINE_LOCK = threading.Lock()


def _extract_reports(state: dict[str, Any]) -> dict[str, str]:
    """Pull the analyst reports out of the final graph state (real content)."""
    reports: dict[str, str] = {}
    for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report"):
        value = state.get(key)
        if value:
            reports[key] = str(value)
    plan = state.get("investment_plan")
    if plan:
        reports["investment_plan"] = str(plan)
    return reports


def _extract_node_trace(events: list[tuple[str, str]]) -> list[dict[str, str]]:
    out = []
    seen: set[str] = set()
    for node, label in events:
        item = {"node": node, "label": label}
        if node in seen:
            item["repeat"] = True
        else:
            seen.add(node)
        out.append(item)
    return out


class TradingDeskEngine:
    """Runs one Trading Desk analysis and produces an honest result record."""

    def __init__(self, *, analysts: tuple[str, ...] = DEFAULT_ANALYSTS):
        self.analysts = tuple(analysts)

    async def run(
        self,
        *,
        symbol: str,
        sel: LLMSelection,
        trade_date: str | None = None,
        max_debate_rounds: int | None = None,
        max_risk_rounds: int | None = None,
        on_step: StepCallback | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the full pipeline for ``symbol`` (StockOS format) and return the result record."""
        if config is None:
            config = await build_engine_config(
                sel,
                max_debate_rounds=max_debate_rounds,
                max_risk_rounds=max_risk_rounds,
            )
        engine_symbol = to_engine_symbol(symbol)
        stockos_symbol = to_stockos_symbol(engine_symbol)
        today = trade_date or date.today().isoformat()

        events: list[tuple[str, str]] = []

        def _step(node: str, label: str, _state: dict[str, Any]) -> None:
            events.append((node, label))
            if on_step is not None:
                try:
                    on_step(node, label, _state)
                except Exception:  # noqa: BLE001
                    logger.warning("on_step callback failed for %s", node, exc_info=True)

        try:
            final_state, rating = await asyncio.to_thread(
                self._run_in_sync,
                config=config,
                engine_symbol=engine_symbol,
                trade_date=today,
                on_step=_step,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Trading engine run failed for %s: %s", engine_symbol, exc)
            raise RuntimeError(f"Trading analysis failed for {symbol}: {exc}") from exc

        decision_md = final_state.get("final_trade_decision", "")
        signal = parse_trading_signal(decision_md, rating)

        options_view = None
        try:
            options_view = await build_options_view(stockos_symbol, signal)
        except Exception as exc:  # noqa: BLE001
            logger.warning("options view skipped for %s: %s", stockos_symbol, exc)

        result = {
            "symbol": stockos_symbol,
            "engine_symbol": engine_symbol,
            "trade_date": today,
            "provider": config["llm_provider"],
            "models": {
                "deep": config["deep_think_llm"],
                "quick": config["quick_think_llm"],
            },
            "rating": signal.rating,
            "signal": signal.to_dict(),
            "options": options_view,
            "final_decision": decision_md,
            "reports": _extract_reports(final_state),
            "node_trace": _extract_node_trace(events),
        }

        persisted = decision_log().record(
            symbol=stockos_symbol,
            engine_symbol=engine_symbol,
            trade_date=today,
            provider=config["llm_provider"],
            deep_model=config["deep_think_llm"],
            quick_model=config["quick_think_llm"],
            final_decision=decision_md,
            rating=signal.rating,
            signal=signal,
            reports=result["reports"],
            node_trace=result["node_trace"],
        )
        result["record_id"] = persisted.get("id")
        return result

    def _run_in_sync(
        self,
        *,
        config: dict[str, Any],
        engine_symbol: str,
        trade_date: str,
        on_step: StepCallback,
    ) -> tuple[dict[str, Any], str]:
        """Stream the graph once. Runs in a worker thread under the global lock."""
        with _ENGINE_LOCK:
            graph = StockTradingAgentsGraph(
                selected_analysts=self.analysts,
                debug=False,
                config=config,
            )
            return graph.run_stream(
                engine_symbol,
                trade_date,
                asset_type="stock",
                on_step=on_step,
            )