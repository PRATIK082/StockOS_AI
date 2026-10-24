"""Unit tests for the Trading Desk integration pieces (no network)."""

from __future__ import annotations

import pytest

from app.services.agents.fundamental import FundamentalAgent
from app.services.agents.momentum import MomentumAgent
from app.services.agents.base import AgentContext
from app.services.tradingagents.options_port import build_options_view
from app.services.tradingagents.signal import TradingSignal, parse_trading_signal
from app.services.tradingagents import store
from app.db.session import SessionFactory


# --- Signal parsing ----------------------------------------------------------


def test_parse_trading_signal_buy() -> None:
    decision = (
        "**Rating**: Buy\n\n"
        "**Executive Summary**: Strong momentum and fair valuation.\n\n"
        "**Investment Thesis**: Upside from sector tailwinds.\n\n"
        "**Price Target**: 125\n\n"
        "**Time Horizon**: 3 months"
    )
    signal = parse_trading_signal(decision, "Buy")
    assert signal.action == "BUY"
    assert signal.direction == "long"
    assert signal.rating == "Buy"
    assert signal.conviction > 0.8
    assert signal.price_target == 125.0
    assert signal.time_horizon == "3 months"


def test_parse_trading_signal_sell() -> None:
    decision = "**Rating**: Sell\n**Executive Summary**: Weak trend."
    signal = parse_trading_signal(decision, "Sell")
    assert signal.action == "SELL"
    assert signal.direction == "short"


def test_parse_trading_signal_empty_falls_back_hold() -> None:
    signal = parse_trading_signal("", None)
    assert signal.rating == "Hold"
    assert signal.action == "HOLD"


# --- Options view (real-chain merge, honest) ---------------------------------


class FakeOptionsMarket:
    """Deterministic chain for NSE:TEST only; others return no chain.

    Biased bullish: calls carry richer premium and higher IV than puts, so
    ``OptionsSignalsService`` reads CALL (call-side bias) on real rows.
    """

    _STRIKES = [23_000, 23_200, 23_400, 23_600, 23_800, 24_000, 24_200]

    async def get_option_chain(self, symbol: str, expiry: str | None = None) -> dict:
        if symbol != "NSE:TEST":
            return {}
        return {
            "spot_price": 23_600.0,
            "expiry": expiry or "2026-08-27",
            "expiries": ["2026-08-27"],
            "calls": [{"strike": k, "last": 150.0, "iv": 0.30} for k in self._STRIKES],
            "puts": [{"strike": k, "last": 100.0, "iv": 0.10} for k in self._STRIKES],
        }


@pytest.fixture
def options_market() -> FakeOptionsMarket:
    return FakeOptionsMarket()


async def test_options_view_skips_non_options_exchanges(options_market) -> None:
    view = await build_options_view("NYSE:AAPL", TradingSignal(rating="Buy"), options_market)
    assert view is None


async def test_options_view_returns_none_when_no_chain(options_market) -> None:
    view = await build_options_view("NSE:FINNIFTY", TradingSignal(rating="Buy"), options_market)
    assert view is None


async def test_options_view_aligned_bullish(options_market) -> None:
    signal = TradingSignal(rating="Buy", direction="long")
    view = await build_options_view("NSE:TEST", signal, options_market)
    assert view is not None
    assert view["available"] is True
    assert view["spot_price"] == 23_600.0
    assert view["alignment"] == "aligned"
    assert view["suggestion"]["leg"] == "call (CE)"
    assert view["suggestion"]["strike"] == 23_600.0
    assert view["suggestion"]["otm_strike"] == 23_800.0
    assert "agree" in view["note"]


async def test_options_view_divergent_bearish(options_market) -> None:
    signal = TradingSignal(rating="Sell", direction="short")
    view = await build_options_view("NSE:TEST", signal, options_market)
    assert view is not None
    assert view["alignment"] == "divergent"
    # Options bias (max pain 23800 > spot 23600) is bullish; the sell call conflicts.
    assert "DISAGREE" in view["note"]


# --- Fixed agents never fabricate ----------------------------------------------


class FakeFundamentalMarket:
    async def get_fundamentals(self, symbol: str) -> dict:
        return {
            "trailingPE": 12.0,
            "priceToBook": 1.2,
            "returnOnEquity": 0.22,
            "revenueGrowth": 0.2,
            "earningsGrowth": 0.25,
            "debtToEquity": 0.3,
            "dividendYield": 0.02,
            "marketCap": 1e12,
            "trailingEps": 5.0,
        }


class EmptyFundamentalMarket:
    async def get_fundamentals(self, symbol: str) -> dict:
        return {}


async def test_fundamental_agent_uses_real_data_only() -> None:
    agent = FundamentalAgent()
    agent.market_service = FakeFundamentalMarket()
    result = await agent.run(AgentContext(symbol="NSE:RELIANCE"))
    assert result.confidence > 0.5
    assert "22.00%" in result.content  # ROE real 0.22 -> 22.00%
    assert "P/E Ratio: 12.00" in result.content
    # Not invented: every number in the report came from the (fake-but-real-shape) feed.
    assert result.data["fundamentals"]["trailingPE"] == 12.0


async def test_fundamental_agent_honest_degradation() -> None:
    agent = FundamentalAgent()
    agent.market_service = EmptyFundamentalMarket()
    result = await agent.run(AgentContext(symbol="NSE:ALPHA"))
    assert result.confidence < 0.5
    assert "will not invent" in result.content.lower()
    assert result.data["fundamentals"] == {}


class EmptyMomentumMarket:
    """Real-shape market service that returns no candles."""

    async def get_history(self, symbol: str, **kwargs) -> dict:
        return {"symbol": symbol, "candles": []}


async def test_momentum_agent_never_fabricates_prices() -> None:
    agent = MomentumAgent()
    agent.market_service = EmptyMomentumMarket()
    result = await agent.run(AgentContext(symbol="NSE:X"))
    # No real history -> honest insufficient data, confidence kept low.
    assert result.confidence < 0.5
    assert "insufficient" in result.content.lower()


# --- Run persistence ---------------------------------------------------------


async def test_delete_run_hard_deletes_nodes() -> None:
    async with SessionFactory() as session:
        first = await store.create_run(
            session,
            user_id="user-a",
            symbol="NSE:X",
            engine_symbol="",
            trade_date="2026-08-09",
            provider="ollama",
            deep_model="m",
            quick_model="q",
        )
        second = await store.create_run(
            session,
            user_id="user-a",
            symbol="NSE:Y",
            engine_symbol="",
            trade_date="2026-08-09",
            provider="ollama",
            deep_model="m",
            quick_model="q",
        )
        await store.add_run_nodes(
            session, first.id, [{"node": "trader_investment_plan", "label": "plan"}]
        )

        # Only the requested run goes away, never the user's other runs.
        assert await store.delete_run(session, first.id, "user-a") is True
        assert await store.get_run(session, first.id, "user-a") is None
        assert await store.get_run(session, second.id, "user-a") is not None
        # Second best-effort delete reports the run is gone.
        assert await store.delete_run(session, first.id, "user-a") is False

        # Someone else's run is never deletable by another user.
        other = await store.create_run(
            session,
            user_id="user-b",
            symbol="NSE:Z",
            engine_symbol="",
            trade_date="2026-08-09",
            provider="ollama",
            deep_model="m",
            quick_model="q",
        )
        assert await store.delete_run(session, other.id, "user-a") is False
        assert await store.get_run(session, other.id, "user-b") is not None