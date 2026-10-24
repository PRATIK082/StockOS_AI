"""Unit tests for the TradingView India options provider (no network calls)."""

from __future__ import annotations

import pytest

from app.services.data.providers.base import OptionsUnavailableError
from app.services.data.providers.tradingview import TradingViewProvider
from app.services.data.providers.yahoo import YahooProvider


def _row(name, expiration, strike, opt_type, theo=10.0, iv=0.2, d=0.5, g=0.001, t=-1.0, v=2.0, rho=0.5):
    return {
        "name": name,
        "root": name[:4],
        "currency": "INR",
        "expiration": expiration,
        "strike": strike,
        "option-type": opt_type,
        "theoPrice": theo,
        "iv": iv,
        "delta": d,
        "gamma": g,
        "theta": t,
        "vega": v,
        "rho": rho,
    }


@pytest.fixture
def provider() -> TradingViewProvider:
    return TradingViewProvider()


def test_leg_mapping(provider: TradingViewProvider) -> None:
    leg = provider._leg(_row("NIFTY260825C24800", 20260825, 24800, "call", theo=120.5, iv=0.18))
    assert leg["strike"] == 24800.0
    assert leg["last"] == 120.5
    assert leg["iv"] == 0.18
    assert leg["delta"] == 0.5
    assert leg["rho"] == 0.5
    assert leg["bid"] is None and leg["ask"] is None
    assert leg["oi"] == 0 and leg["volume"] == 0


def test_leg_skips_invalid(provider: TradingViewProvider) -> None:
    assert provider._leg({"strike": None, "option-type": "call"}) is None
    assert provider._leg({"strike": 100, "option-type": "foo"}) is None


def test_to_iso(provider: TradingViewProvider) -> None:
    assert provider._to_iso(20260825) == "2026-08-25"
    assert provider._to_iso("20260825") == "2026-08-25"
    assert provider._to_iso("2026-08-25") == "2026-08-25"
    assert provider._to_iso(None) is None


def test_pick_expiry_requested(provider: TradingViewProvider) -> None:
    exps = ["2026-08-11", "2026-08-25", "2026-09-29"]
    assert provider._pick_expiry(exps, "2026-08-25") == "2026-08-25"


def test_pick_expiry_missing_uses_nearest(provider: TradingViewProvider) -> None:
    exps = ["2026-08-11", "2026-08-25"]
    assert provider._pick_expiry(exps, "2026-01-01") == "2026-08-11"
    assert provider._pick_expiry(exps, "2026-08-30") == "2026-08-25"


def test_pick_expiry_default_is_upcoming(provider: TradingViewProvider) -> None:
    exps = ["2020-01-01", "2030-06-26", "2030-12-24"]
    assert provider._pick_expiry(exps, None) == "2030-06-26"


def test_atm_strike(provider: TradingViewProvider) -> None:
    calls = [{"strike": 24800.0, "iv": 0.30}, {"strike": 24850.0, "iv": 0.12}]
    puts = [{"strike": 24800.0, "iv": 0.31}, {"strike": 24850.0, "iv": 0.11}]
    assert provider._atm_strike(calls, puts) == 24850.0


@pytest.mark.asyncio
async def test_get_option_chain_builds(provider: TradingViewProvider, monkeypatch) -> None:
    exp_rows = [{"expiration": 20260811}, {"expiration": 20260825}, {"expiration": 20260929}]
    leg_rows = [
        _row("NIFTY260825C24800", 20260825, 24800, "call", theo=120.5, iv=0.18),
        _row("NIFTY260825P24800", 20260825, 24800, "put", theo=115.0, iv=0.19),
    ]

    async def fake_fetch(underlying, *, columns, expiry=None):
        if columns == ["expiration"]:
            return exp_rows
        return [r for r in leg_rows if r["expiration"] == expiry]

    async def fake_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 24774.3}

    monkeypatch.setattr(provider, "_fetch_scan", fake_fetch)
    monkeypatch.setattr(YahooProvider, "get_quote", fake_quote)

    chain = await provider.get_option_chain("NSE:NIFTY", expiry="2026-08-25")
    assert chain["symbol"] == "NSE:NIFTY"
    assert chain["expiry"] == "2026-08-25"
    assert chain["expiries"] == ["2026-08-11", "2026-08-25", "2026-09-29"]
    assert chain["spot_price"] == 24774.3
    assert len(chain["calls"]) == 1 and len(chain["puts"]) == 1
    assert chain["calls"][0]["strike"] == 24800.0
    assert chain["calls"][0]["last"] == 120.5
    assert chain["provider"] == "tradingview"


@pytest.mark.asyncio
async def test_get_option_chain_default_expiry(provider: TradingViewProvider, monkeypatch) -> None:
    exp_rows = [{"expiration": 20300625}, {"expiration": 20301224}]
    leg_rows = [_row("NIFTY300625C24800", 20300625, 24800, "call", theo=10.0, iv=0.2)]

    async def fake_fetch(underlying, *, columns, expiry=None):
        if columns == ["expiration"]:
            return exp_rows
        return leg_rows

    async def fake_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 24774.3}

    monkeypatch.setattr(provider, "_fetch_scan", fake_fetch)
    monkeypatch.setattr(YahooProvider, "get_quote", fake_quote)

    chain = await provider.get_option_chain("NSE:NIFTY")
    assert chain["expiry"] == "2030-06-25"
    assert len(chain["calls"]) == 1


@pytest.mark.asyncio
async def test_get_option_chain_unsupported_exchange(provider: TradingViewProvider) -> None:
    with pytest.raises(OptionsUnavailableError):
        await provider.get_option_chain("NYSE:AAPL")


@pytest.mark.asyncio
async def test_engine_chain_without_oi_degrades_gracefully() -> None:
    """The engine must not fabricate max pain / PCR when a provider has no OI."""
    from app.services.options.engine import OptionsEngine

    class FakeService:
        async def get_option_chain(self, symbol: str, *, expiry: str | None = None) -> dict:
            return {
                "symbol": "NSE:TCS",
                "expiry": "2026-08-25",
                "expiries": ["2026-08-25", "2026-09-29"],
                "spot_price": 2473.7,
                "calls": [
                    {"strike": 2500.0, "bid": None, "ask": None, "last": 30.5, "volume": 0, "oi": 0, "iv": 0.27}
                ],
                "puts": [
                    {"strike": 2450.0, "bid": None, "ask": None, "last": 28.0, "volume": 0, "oi": 0, "iv": 0.25}
                ],
                "provider": "tradingview",
            }

    engine = OptionsEngine(market_service=FakeService())
    chain = await engine.get_option_chain("NSE:TCS")
    assert chain.spot_price == 2473.7
    assert chain.max_pain is None
    assert chain.pcr is None
    assert chain.iv_rank >= 0
    assert chain.expiries == ["2026-08-25", "2026-09-29"]
