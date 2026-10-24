"""Regression tests for the market-data fallback chain: bare tickers auto-
resolve to their universe-canonical exchange form when the default chain has no
data, and degrade honestly otherwise (no fabricated candles, no crash)."""

from __future__ import annotations

import asyncio

import pytest


async def _fake_fetch(providers, method, symbol, chain, *args, **kwargs):
    """Deterministic fake chain: only `NSE:RELIANCE` and `NSE:TCS` have data."""
    if symbol.upper() in ("NSE:RELIANCE", "NSE:TCS"):
        return (
            {
                "candles": [
                    {
                        "ts": f"2024-01-{i:02d}T00:00:00+05:30",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.0,
                        "volume": 1_000_000,
                    }
                    for i in range(1, 40)
                ]
            },
            "tradingview",
        )
    return {}, "yahoo: no data"


def test_bare_ticker_auto_resolves_to_nse(monkeypatch) -> None:
    import app.services.data.fallback as fb
    from app.services.data.service import market_data

    monkeypatch.setattr(fb, "fetch_with_chain", _fake_fetch)

    async def _run() -> dict:
        return await market_data.get_history_auto("RELIANCE", interval="1d", period="1y")

    h = asyncio.run(_run())
    assert len(h.get("candles", [])) == 39
    assert h.get("symbol") == "NSE:RELIANCE"
    assert h.get("source") == "tradingview"


def test_bare_ticker_degrades_honestly(monkeypatch) -> None:
    """A bare ticker that resolves nowhere returns an empty history + error,
    never a fabricated or crashing result."""
    import app.services.data.fallback as fb
    from app.services.data.service import market_data

    monkeypatch.setattr(fb, "fetch_with_chain", _fake_fetch)

    async def _run() -> dict:
        return await market_data.get_history_auto("DEFINITELYNOTATICKER", interval="1d", period="1y")

    h = asyncio.run(_run())
    assert h.get("candles") == []
    assert "error" in h or h.get("source")
