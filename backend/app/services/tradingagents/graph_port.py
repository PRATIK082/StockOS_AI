"""StockOS-flavoured TradingAgents graph.

Subclasses the vendored ``TradingAgentsGraph`` so that:

- Data tool nodes are the StockOS ports from :mod:`.data_port` (the engine
  analyses real StockOS data instead of the vendored yfinance/AV tools).
- An optional per-user ``api_key`` in the config is forwarded to the provider
  LLM clients via kwargs (the vendored ``_PASSTHROUGH_KWARGS`` path) — never by
  mutating environment variables.
- A streaming runner exposes the actual LangGraph node names for the Trading
  Desk's live status panel instead of hiding behind the vendored ``invoke``.

The vendored reflection/signal-processing modules are unchanged.
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.prebuilt import ToolNode

from tradingagents.graph.trading_graph import TradingAgentsGraph

from app.core.logging import get_logger
from app.services.tradingagents.data_port import TOOL_NODES

logger = get_logger("tradingagents.graph_port")

# Node label -> human readable step, used for live status messages.
_NODE_LABELS = {
    "Market Analyst": "Market analyst",
    "Sentiment Analyst": "Sentiment analyst",
    "News Analyst": "News analyst",
    "Fundamentals Analyst": "Fundamentals analyst",
    "tools_market": "Fetching market data",
    "tools_social": "Fetching sentiment data",
    "tools_news": "Fetching news",
    "tools_fundamentals": "Fetching fundamentals",
    "Bull Researcher": "Bull researcher",
    "Bear Researcher": "Bear researcher",
    "Research Manager": "Research manager",
    "Trader": "Trader",
    "Aggressive Analyst": "Aggressive analyst",
    "Neutral Analyst": "Neutral analyst",
    "Conservative Analyst": "Conservative analyst",
    "Portfolio Manager": "Portfolio manager",
    "Msg Clear Market": "Clearing market messages",
    "Msg Clear Sentiment": "Clearing sentiment messages",
    "Msg Clear News": "Clearing news messages",
    "Msg Clear Fundamentals": "Clearing fundamentals messages",
}

# Analyst keys active in the default (fixed) engine pipeline. The vendored
# graph also supports "social" as a wire key (Sentiment analyst).
DEFAULT_ANALYSTS = ("market", "social", "news", "fundamentals")

StepCallback = Callable[[str, str, dict[str, Any]], None]


class StockTradingAgentsGraph(TradingAgentsGraph):
    """TradingAgentsGraph with StockOS data tools and per-user provider keys."""

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        return {name: ToolNode(tools) for name, tools in TOOL_NODES.items()}

    def _get_provider_kwargs(self) -> dict[str, Any]:
        kwargs = super()._get_provider_kwargs()
        api_key = self.config.get("api_key")
        if api_key:
            kwargs["api_key"] = api_key
            logger.debug("Applying per-user api_key for provider '%s'", self.config.get("llm_provider"))
        return kwargs

    def _resolve_pending_entries(self, ticker: str) -> None:
        # Reflection/outcome resolution over yfinance is intentionally disabled:
        # StockOS keeps the engine on the StockOS data source. Decision entries
        # are still recorded; past-context stays empty until a later phase wires
        # reflections off the local decision store.
        return

    def _run_graph_stream(
        self,
        company_name: str,
        trade_date: str,
        asset_type: str = "stock",
        on_step: StepCallback | None = None,
    ) -> dict[str, Any]:
        """Stream the compiled graph once, yielding per-node state updates.

        Mirrors the vendored ``_run_graph`` bookkeeping (log state to disk,
        store decision to memory log) while surfacing the true node names
        through ``on_step``. Uses the vendored propagator + memory log so the
        observable behaviour stays identical to a plain ``propagate`` call.
        """
        past_context = self.memory_log.get_past_context(company_name)
        instrument_context = self.resolve_instrument_context(company_name, asset_type)
        init_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=past_context,
            instrument_context=instrument_context,
        )
        args = self.propagator.get_graph_args()
        # "updates" mode yields (node -> {channel: value}) per step. That gives
        # us real per-node labels for the live panel and lets us merge the
        # cumulative state safely (the propagator's default "values" mode yields
        # raw cumulative dicts whose shape we'd have to guess at).
        args["stream_mode"] = "updates"

        merged: dict[str, Any] = dict(init_state)
        for chunk in self.graph.stream(init_state, **args):
            if not isinstance(chunk, dict):
                continue
            for node, updates in chunk.items():
                if on_step is not None:
                    label = _NODE_LABELS.get(node, node)
                    on_step(node, label, updates or {})
                if isinstance(updates, dict):
                    merged.update(updates)

        final_state = merged

        self.curr_state = final_state
        self.ticker = company_name
        self._log_state(trade_date, final_state)
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )
        return final_state

    def run_stream(
        self,
        company_name: str,
        trade_date: str,
        asset_type: str = "stock",
        on_step: StepCallback | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Run the pipeline and return (final_state, 5-tier rating)."""
        final_state = self._run_graph_stream(
            company_name, trade_date, asset_type=asset_type, on_step=on_step
        )
        return final_state, self.process_signal(final_state["final_trade_decision"])