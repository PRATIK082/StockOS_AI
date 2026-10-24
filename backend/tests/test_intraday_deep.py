"""Tests for the intraday board, options-coverage probe and deep analysis engines.

Engine-level tests with injected fakes — no network or database touched.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.analysis import intraday as intraday_mod
from app.services.analysis.intraday import IntradayBoard, clamp_period
from app.services.deep import engine as deep_mod
from app.services.deep.engine import DeepAnalysisEngine
from app.services.technical.indicators import TechnicalIndicators


# ------------------------------------------------------------------------------------- utils

def _candles(days: int = 2, per_day: int = 4, base: float = 100.0) -> list[dict]:
    out: list[dict] = []
    for d in range(days):
        for i in range(per_day):
            c = base * (1 + d * 0.01) + i * 0.1
            out.append(
                {
                    "ts": f"2025-06-{(d + 10):02d}T10:{(i * 15):02d}:00",
                    "open": c,
                    "high": c * 1.01,
                    "low": c * 0.99,
                    "close": c,
                    "volume": 1000,
                }
            )
    return out


class _FakeMarket:
    def __init__(self, ok: dict[str, list[dict]] | None = None) -> None:
        self.ok = ok or {"NSE:A": _candles(days=2, base=100.0), "NSE:B": _candles(days=2, base=200.0)}

    async def get_history_auto(self, symbol: str, *, interval: str, period: str) -> dict:
        if symbol not in self.ok:
            raise RuntimeError("boom no candles")
        return {"symbol": symbol, "interval": interval, "period": period, "candles": self.ok[symbol]}

    async def get_quote(self, symbol: str, provider: str | None = None) -> dict:
        return {"symbol": symbol, "price": 123.45, "day_change_pct": 0.5, "currency": "INR", "provider": "yahoo"}

    async def get_option_chain(self, symbol: str, *, expiry: str | None = None) -> dict:
        return {"symbol": symbol, "spot_price": 123.45, "calls": [], "puts": []}


def _fake_symbols() -> list[dict]:
    return [
        {"symbol": "NSE:NIFTY", "name": "NIFTY 50", "market": "india", "currency": "INR", "index": True},
        {"symbol": "NSE:A", "name": "Stock A", "market": "india", "currency": "INR", "index": False},
        {"symbol": "NSE:B", "name": "Stock B", "market": "india", "currency": "INR", "index": False},
        {"symbol": "NSE:ERR", "name": "Broken", "market": "india", "currency": "INR", "index": False},
    ]


# --------------------------------------------------------------------------------- intraday

@pytest.mark.asyncio
async def test_intraday_board_shape_and_derivation(monkeypatch) -> None:
    fake = _FakeMarket(ok={
        "NSE:NIFTY": _candles(days=2, base=25000.0),
        "NSE:A": _candles(days=2, base=100.0),
        "NSE:B": _candles(days=2, base=200.0),
    })
    monkeypatch.setattr(intraday_mod, "by_market", lambda market: _fake_symbols())
    board = await IntradayBoard(market_service=fake).board(market="india", interval="1m", period="5d")

    assert board["market"] == "india"
    assert board["interval"] == "1m"
    assert board["period"] == "5d"
    assert board["generated_at"]
    assert board["total"] == 4
    assert board["errors"] == 1

    rows = {r["symbol"]: r for r in board["rows"]}
    a = rows["NSE:A"]
    assert a["last"] == pytest.approx(100.0 + 0.01 * 100.0 + 3 * 0.1)
    assert a["change_pct"] is not None
    assert a["day_volume"] == pytest.approx(4000)
    assert len(a["sparkline"]) == 4
    assert a["high"] and a["low"]
    assert a["index"] is False

    err = rows["NSE:ERR"]
    assert err["last"] is None
    assert "boom" in (err["error"] or "")
    assert err["sparkline"] == []

    # Indices first, then by strength of the day's move.
    ordered = [r["symbol"] for r in board["rows"]]
    assert ordered[0] == "NSE:NIFTY"
    assert "NSE:ERR" in ordered[1:]


@pytest.mark.asyncio
async def test_intraday_board_limit_and_clamp(monkeypatch) -> None:
    monkeypatch.setattr(intraday_mod, "by_market", lambda market: _fake_symbols())
    board = await IntradayBoard(market_service=_FakeMarket()).board(market="india", interval="1m", period="5d", limit=2)
    assert board["total"] <= 2


def test_clamp_period() -> None:
    assert clamp_period("1m", "1y") == "5d"
    assert clamp_period("5m", "6mo") == "1mo"
    assert clamp_period("1h", "5y") == "1y"
    assert clamp_period("1h", "5d") == "5d"
    assert clamp_period("1d", "1y") == "1y"
    assert clamp_period("5m", "garbage") == "1mo"


# ----------------------------------------------------------------------------------- deep

def _deep_body(**over) -> SimpleNamespace:
    base = {
        "symbols": ["NSE:RELIANCE", "NSE:TCS"],
        "question": "Which is a better momentum trade?",
        "include": ["quote", "technical", "options", "prediction"],
        "provider": None,
        "stream": True,
    }
    base.update(over)
    return SimpleNamespace(**base)


class _FakePredictionResult:
    def __init__(self) -> None:
        self.symbol = "NSE:X"
        self.timeframe = "week"
        self.current_price = 100.0
        self.predicted_price = 105.0
        self.confidence = 0.72
        self.expected_return = 0.05
        self.bear_case = {"target": 95.0, "reason": "bear"}
        self.base_case = {"target": 105.0, "reason": "base"}
        self.bull_case = {"target": 112.0, "reason": "bull"}
        self.action = "BUY"
        self.horizon = "1w"
        self.factors = {"momentum": 0.8, "rsi": 62, "trend": 1}


class _FakePrediction:
    async def predict(self, symbol: str, timeframe, **kw):
        return _FakePredictionResult()


async def _collect(engine: DeepAnalysisEngine, body) -> dict:
    events: list[dict] = []
    async for ev in engine.stream(body):
        events.append(ev)
    return events


async def _fake_chat(*a, **k):
    return "### rank\n1. A\n\n*Research only, not investment advice.*"


async def _fake_signals(symbol: str):
    return {"bias": "CALL", "atm_iv": 0.19, "expiry": "2026-08-25"}


@pytest.mark.asyncio
async def test_deep_stream_emits_plan_stages_answer(monkeypatch) -> None:
    ok = {
        "NSE:RELIANCE": _candles(days=2, base=2500.0),
        "NSE:TCS": _candles(days=2, base=4000.0),
    }
    eng = DeepAnalysisEngine(market_service=_FakeMarket(ok=ok), prediction=_FakePrediction())
    eng.signals = SimpleNamespace(signals=_fake_signals)
    monkeypatch.setattr(deep_mod, "gateway", SimpleNamespace(chat=_fake_chat))

    events = await _collect(eng, _deep_body())

    assert events[0]["type"] == "plan"
    assert "answer" in [e["key"] for e in events[0]["plan"]]
    stages = [e for e in events if e["type"] == "stage"]
    keys = {e["key"] for e in stages}
    assert "NSE:RELIANCE|quote" in keys
    assert "NSE:RELIANCE|technical" in keys
    assert "NSE:RELIANCE|options" in keys
    assert "NSE:RELIANCE|prediction" in keys
    assert all(e["status"] == "done" for e in stages)

    ans = events[-1]
    assert ans["type"] == "answer"
    assert "rank" in ans["data"]["answer"]
    assert ans["data"]["confidence"] == pytest.approx(0.72)
    assert "NSE:RELIANCE, NSE:TCS" in ans["data"]["symbol"]
    assert ans["data"]["sources"]
    assert any("technical" in s for s in ans["data"]["sources"])


@pytest.mark.asyncio
async def test_deep_falls_back_to_deterministic_verdict(monkeypatch) -> None:
    ok = {"NSE:RELIANCE": _candles(), "NSE:TCS": _candles(base=200.0)}
    eng = DeepAnalysisEngine(market_service=_FakeMarket(ok=ok), prediction=_FakePrediction())
    eng.signals = SimpleNamespace(signals=lambda sym: _raise_boom())

    def _raise_boom(*a, **k):
        raise RuntimeError("chain unavailable")

    eng.signals = SimpleNamespace(signals=_raise_boom)
    monkeypatch.setattr(deep_mod, "gateway", SimpleNamespace(chat=_raise_boom))

    events = await _collect(eng, _deep_body())

    ans = events[-1]["data"]
    assert "Deep analysis" in ans["answer"]
    assert "LLM verdict unavailable" in ans["answer"]
    # Options stage degrades to skipped, not a crash.
    options_stage = [e for e in events if e["type"] == "stage" and e["key"].endswith("|options")][0]
    assert options_stage["status"] == "skipped"
    assert "Research only" in ans["answer"]


@pytest.mark.asyncio
async def test_deep_resolves_bare_symbol(monkeypatch) -> None:
    eng = DeepAnalysisEngine(market_service=_FakeMarket(ok={"NSE:RELIANCE": _candles()}), prediction=_FakePrediction())
    monkeypatch.setattr(deep_mod, "gateway", SimpleNamespace(chat=_fake_chat))

    events = await _collect(eng, _deep_body(symbols=["RELIANCE"]))
    plan_keys = [e["key"] for e in events[0]["plan"]]
    assert plan_keys == ["NSE:RELIANCE", "answer"]


@pytest.mark.asyncio
async def test_deep_run_collects_payload(monkeypatch) -> None:
    eng = DeepAnalysisEngine(market_service=_FakeMarket(ok={"NSE:RELIANCE": _candles(), "NSE:TCS": _candles(base=200.0)}), prediction=_FakePrediction())
    eng.signals = SimpleNamespace(signals=lambda sym: {})
    monkeypatch.setattr(deep_mod, "gateway", SimpleNamespace(chat=_fake_chat))
    result = await eng.run(_deep_body(include=["technical", "prediction"]))
    assert result["plan"]
    assert len(result["stages"]) == 4  # 2 symbols × technical+prediction
    assert result["answer"]["answer"]


# --------------------------------------------------------------------- new indicator series

def _synthetic_candles(n: int = 140) -> tuple[list[float], list[float], list[float], list[float]]:
    closes = [100 + i * 0.5 + (10 if i > n // 2 else 0) for i in range(n)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    vols = [1_000_000 + i * 1000 for i in range(n)]
    return closes, highs, lows, vols


def test_supertrend_and_stoch_series() -> None:
    closes, highs, lows, _ = _synthetic_candles()
    st = TechnicalIndicators.supertrend_series(highs, lows, closes, period=10, multiplier=3.0)
    assert "value" in st and "trend" in st
    assert len(st["trend"]) == len(closes)
    assert st["trend"][-1] in {"buy", "sell"}

    stoch = TechnicalIndicators.stoch_series(highs, lows, closes, period=14, d_smooth=3)
    for v in stoch["%K"][-10:]:
        assert 0 <= v <= 100


def test_dmi_cci_mfi_wr_obv_sar_ichimoku() -> None:
    closes, highs, lows, vols = _synthetic_candles()
    dmi = TechnicalIndicators.dmi_series(highs, lows, closes, period=14)
    assert set(dmi.keys()) == {"adx", "plus_di", "minus_di"}
    assert dmi["adx"][-1] is not None

    assert TechnicalIndicators.cci_series(highs, lows, closes, 20)[-1] is not None
    mfi = TechnicalIndicators.mfi_series(highs, lows, closes, vols, 14)
    assert 0 <= mfi[-1] <= 100
    assert TechnicalIndicators.williams_r_series(highs, lows, closes, 14)[-1] is not None

    sar = TechnicalIndicators.psar_series(highs, lows)
    assert len(sar) == len(closes) and sar[-1] is not None

    ichi = TechnicalIndicators.ichimoku_series(highs, lows, closes)
    assert {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou"} <= set(ichi.keys())
    assert len(ichi["kijun"]) == len(closes)


def test_signal_markers_fire_on_trend_flip() -> None:
    closes, highs, lows, vols = _synthetic_candles()
    ind = TechnicalIndicators
    sma20 = ind.sma_series(closes, 20)
    sma50 = ind.sma_series(closes, 50)
    rsi = ind.rsi_series(closes, 14)
    macd = ind.macd_series(closes)
    stoch = ind.stoch_series(highs, lows, closes)
    markers = ind.signal_markers(
        [{"ts": f"2025-01-{i % 28 + 1:02d}", "close": c} for i, c in enumerate(closes)],
        sma20, sma50, rsi, macd["macd"], macd["signal"], stoch["%K"], stoch["%D"],
    )
    assert markers
    for m in markers:
        assert m["type"] in {"buy", "sell"}
        assert m["reason"] and m["price"] and m["time"]
    assert all(m["type"] == "sell" for m in markers[-1:]) or all(m["type"] == "buy" for m in markers[-1:])