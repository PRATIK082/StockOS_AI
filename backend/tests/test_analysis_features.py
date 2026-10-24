"""Unit tests for prediction trading stats, options signals, and sector analysis (no network)."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.agents.stock_analysis import StockAnalysisAgent
from app.services.analysis.sectors import SectorAnalysisService, cap_class
from app.services.options.signals import OptionsSignalsService
from app.services.prediction.engine import PredictionEngine, Timeframe
from app.services.technical.indicators import TechnicalIndicators


def _closes(n: int = 200) -> list[float]:
    tick = 200.0
    out: list[float] = []
    for i in range(n):
        tick += np.sin(i / 7.0) * 1.5 + (0.02 if i % 2 else -0.02)
        out.append(round(tick, 2))
    return out


def _candles(closes: np.ndarray) -> list[dict]:
    n = len(closes)
    return [
        {
            "ts": "2026-01-01T00:00:00",
            "open": float(closes[i]),
            "high": float(closes[i]) + 1.0,
            "low": float(closes[i]) - 1.0,
            "close": float(closes[i]),
            "volume": int(2_000_000 if i == n - 1 else 1_000_000),
        }
        for i in range(n)
    ]


class FakeMarketService:
    """Deterministic data source: UP trends up, DOWN trends down, FLAT is flat."""

    _SERIES = {
        "NSE:UP": np.linspace(100.0, 130.0, 260),
        "NSE:DOWN": np.linspace(100.0, 70.0, 260),
        "NSE:FLAT": np.full(260, 100.0),
    }

    async def get_history(self, symbol: str, **kwargs) -> dict:
        return {"symbol": symbol, "candles": _candles(self._SERIES[symbol])}

    async def get_quote(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "name": symbol,
            "price": float(self._SERIES[symbol][-1]),
            "day_change_pct": {"NSE:UP": 2.5, "NSE:DOWN": -2.5, "NSE:FLAT": 0.0}[symbol],
            "sector": "Technology",
            "market_cap": 3e12,
        }

    async def get_fundamentals(self, symbol: str) -> dict:
        if symbol == "NSE:DOWN":
            return {
                "trailingPE": 40.0, "priceToBook": 4.0, "returnOnEquity": 0.02,
                "profitMargins": 0.01, "sector": "Technology", "industry": "Software",
                "marketCap": 3e12,
            }
        return {
            "trailingPE": 15.0,
            "priceToBook": 2.0,
            "returnOnEquity": 0.18,
            "profitMargins": 0.1,
            "sector": "Technology",
            "industry": "Software",
            "marketCap": 3e12,
        }


@pytest.fixture
def engine() -> PredictionEngine:
    return PredictionEngine(market_service=FakeMarketService())


# --- Prediction trading stats ------------------------------------------------

async def test_prediction_returns_real_trading_stats(engine: PredictionEngine) -> None:
    result = await engine.predict("NSE:UP", Timeframe.WEEK)
    s = result.trading_stats
    assert s["trading_days"] == 260
    assert s["up_days"] > s["down_days"]
    assert s["up_ratio"] is not None and 0.0 < s["up_ratio"] <= 1.0
    assert s["avg_volume"] > 0
    assert s["atr"] > 0
    assert s["low_52w"] == 100.0 and s["high_52w"] == 130.0
    assert s["sector"] == "Technology"
    assert s["industry"] == "Software"
    assert s["cap_class"] == "MEGA"
    assert s["price_band"] == "LOW"


async def test_prediction_action_and_horizon(engine: PredictionEngine) -> None:
    up = await engine.predict("NSE:UP", Timeframe.WEEK)
    down = await engine.predict("NSE:DOWN", Timeframe.WEEK)
    assert up.action == "BUY"
    assert down.action == "SELL"
    assert up.horizon == "Short-term"
    long = await engine.predict("NSE:UP", Timeframe.YEAR)
    assert long.horizon == "Long-term"


def _candles_from(closes: np.ndarray, volumes: list[int] | None = None) -> list[dict]:
    return [
        {
            "ts": "2026-01-01T00:00:00",
            "open": float(closes[i]),
            "high": float(closes[i]) + 1.0,
            "low": float(closes[i]) - 1.0,
            "close": float(closes[i]),
            "volume": (volumes[i] if volumes else 1_000_000),
        }
        for i in range(len(closes))
    ]


class FakeChainMarket(FakeMarketService):
    """FakeMarketService plus a deterministic option chain for one symbol."""

    async def get_option_chain(self, symbol: str, **kwargs) -> dict:
        spot = float(self._SERIES[symbol][-1])
        strikes = [round(spot - 20 + 5 * i, 2) for i in range(9)]
        return {
            "symbol": symbol,
            "expiry": "2026-08-27",
            "expiries": ["2026-08-27", "2026-09-24"],
            "spot_price": spot,
            "calls": [
                {"strike": k, "last": max(spot - k, 1.0), "iv": 0.20 + 0.01 * (k - (spot - 20))}
                for k in strikes
            ],
            "puts": [
                {"strike": k, "last": max(k - spot, 1.0), "iv": 0.28 + 0.01 * ((spot + 20) - k)}
                for k in strikes
            ],
        }


async def test_prediction_stats_include_options_snapshot() -> None:
    engine = PredictionEngine(market_service=FakeChainMarket())
    result = await engine.predict("NSE:UP", Timeframe.WEEK)
    s = result.trading_stats
    assert s["options"] is not None
    assert s["options"]["bias"] in {"CALL", "PUT", "NEUTRAL"}
    assert s["options"]["expiry"] == "2026-08-27"
    assert s["options"]["max_pain"] is not None
    assert s["last_expiry"] == "2026-08-27"


async def test_prediction_without_chain_has_null_options(engine: PredictionEngine) -> None:
    result = await engine.predict("NSE:UP", Timeframe.WEEK)
    assert result.trading_stats["options"] is None


async def test_option_leg_exposes_available_strikes_and_expiries() -> None:
    engine = PredictionEngine(market_service=FakeChainMarket())
    leg = await engine._build_option_leg(
        "NSE:UP",
        {},
        {"type": "CE", "strike": 130.0, "expiry": "2026-08-27"},
        underlying_return=0.05,
    )
    assert leg is not None
    assert leg["expiry"] == "2026-08-27"
    assert leg["available_expiries"] == ["2026-08-27", "2026-09-24"]
    assert len(leg["available_strikes"]) > 0
    assert leg["current_premium"] > 0
    assert leg["predicted_premium"] > 0


def test_theoretical_price_call_vs_put() -> None:
    from app.services.options.engine import OptionsEngine

    engine = OptionsEngine()
    call = engine.theoretical_price(100.0, 100.0, 30 / 365, 0.25, "call")
    put = engine.theoretical_price(100.0, 100.0, 30 / 365, 0.25, "put")
    assert call > 0
    assert put > 0
    assert abs(call - put) < 1.5  # near-ATM call/put roughly aligned
    # Deep ITM call is worth at least intrinsic value.
    deep = engine.theoretical_price(120.0, 100.0, 30 / 365, 0.25, "call")
    assert deep >= 20.0 - 1e-6
    # Zero volatility behaves like intrinsic value.
    zero_iv = engine.theoretical_price(100.0, 100.0, 30 / 365, 0.0, "call")
    assert zero_iv == 0.0


async def test_option_leg_uses_nearest_strike_when_requested_missing() -> None:
    engine = PredictionEngine(market_service=FakeChainMarket())
    leg = await engine._build_option_leg(
        "NSE:UP",
        {},
        {"type": "PE", "strike": 99999.0, "expiry": None},
        underlying_return=-0.03,
    )
    assert leg is not None
    assert leg["strike"] in leg["available_strikes"]


async def test_agent_reasoning_falls_back_when_llm_down(monkeypatch) -> None:
    from app.services.agents import stock_analysis as sa_mod

    async def _unreachable(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(sa_mod.gateway, "chat", _unreachable)
    payload = {
        "symbol": "NSE:UP",
        "quote": {"price": 130.0, "name": "Up Co"},
        "fundamentals": {"trailingPE": 15.0, "returnOnEquity": 0.18},
        "indicators": {"trend": "bullish", "rsi_14": 62.0},
        "trading_stats": {
            "up_days": 160, "down_days": 99, "trading_days": 260,
            "avg_volume": 1_000_000, "volume_trend": 1.2, "atr": 2.0,
            "range_52w_position": 0.75, "low_52w": 100.0, "high_52w": 130.0,
            "cap_class": "MEGA", "last_expiry": "2026-08-27",
        },
        "options": {"bias": "CALL", "max_pain": 128.0, "spot_price": 130.0, "atm_iv": 0.21},
        "prediction": {"action": "BUY", "horizon": "Short-term", "bull_case": 136.0, "bear_case": 124.0},
        "history_candles": 260,
        "recent_closes": [125.0, 126.0, 127.0, 128.0, 129.0],
    }
    text = await StockAnalysisAgent()._analyze("NSE:UP", payload)
    assert "BUY" in text
    assert "MEGA" in text
    assert "CALL" in text
    assert "160 up days" in text
    assert "not investment advice" in text.lower()


def test_agent_fallback_is_data_backed() -> None:
    text = StockAnalysisAgent._fallback({
        "symbol": "NSE:X",
        "quote": {"price": 250.0, "name": "Test Ltd"},
        "trading_stats": {
            "up_days": 30, "down_days": 20, "trading_days": 50,
            "avg_volume": 500_000, "volume_trend": 1.1, "atr": 5.0,
            "range_52w_position": 0.6, "low_52w": 200.0, "high_52w": 300.0,
            "cap_class": "LARGE",
        },
        "prediction": {"action": "BUY", "horizon": "Short-term", "bull_case": 260.0, "base_case": 255.0, "bear_case": 245.0},
        "options": {"bias": "CALL", "max_pain": 252.0},
    })
    assert "Test Ltd" in text
    assert "BUY" in text
    assert "LARGE" in text
    assert "CALL" in text
    assert "260.00" in text
    assert "252" in text


def test_cap_class_thresholds() -> None:
    assert cap_class(1e9, "NSE:X") == "SMALL"
    assert cap_class(2e11, "NSE:X") == "MID"
    assert cap_class(2e12, "NSE:X") == "LARGE"
    assert cap_class(4e12, "NSE:X") == "MEGA"
    assert cap_class(None, "NSE:X") == "n/a"
    assert cap_class(1e9, "NYSE:X") == "SMALL"
    assert cap_class(5e9, "NASDAQ:X") == "MID"
    assert cap_class(5e10, "NYSE:X") == "LARGE"
    assert cap_class(3e11, "NYSE:X") == "MEGA"


def test_price_band() -> None:
    assert PredictionEngine._price_band(50) == "LOW"
    assert PredictionEngine._price_band(500) == "MID"
    assert PredictionEngine._price_band(5000) == "HIGH"


# --- Indicator series (charted deterministically over real candles) ---------

def test_series_alignment_and_length() -> None:
    closes = _closes(200)
    s = TechnicalIndicators
    assert len(s.sma_series(closes, 20)) == 200
    assert len(s.ema_series(closes, 20)) == 200
    assert len(s.rsi_series(closes, 14)) == 200
    macd = s.macd_series(closes)
    assert set(macd) == {"macd", "signal", "histogram"}
    bb = s.bollinger_series(closes)
    assert set(bb) == {"upper", "middle", "lower"}


def test_series_are_null_until_warmup() -> None:
    s = TechnicalIndicators
    sma = s.sma_series(_closes(30), 20)
    assert sma[18] is None
    assert sma[19] is not None and sma[-1] is not None
    rsi = s.rsi_series(_closes(30), 14)
    assert rsi[13] is None
    assert rsi[14] is not None


def test_macd_histogram_balances_lines() -> None:
    closes = _closes(120)
    macd = TechnicalIndicators.macd_series(closes)
    for i in range(100, 120):
        if macd["macd"][i] is not None and macd["signal"][i] is not None:
            assert macd["histogram"][i] == pytest.approx(macd["macd"][i] - macd["signal"][i])


def test_bollinger_bands_middle_is_sma() -> None:
    closes = _closes(40)
    bb = TechnicalIndicators.bollinger_series(closes, 20)
    sma = TechnicalIndicators.sma_series(closes, 20)
    assert bb["middle"][-1] == pytest.approx(sma[-1])
    assert bb["upper"][-1] >= bb["middle"][-1] >= bb["lower"][-1]


def test_atr_from_candles() -> None:
    atr = PredictionEngine._calculate_atr(_candles(np.linspace(100, 130, 260)))
    assert atr == pytest.approx(2.0, abs=0.1)


# --- Options signals ---------------------------------------------------------

def _fake_chain(spot: float = 100.0) -> dict:
    strikes = [90, 95, 100, 105, 110]
    return {
        "symbol": "NSE:X",
        "expiry": "2026-08-27",
        "expiries": ["2026-08-27", "2026-09-24"],
        "spot_price": spot,
        "calls": [
            {"strike": k, "last": max(spot - k, 1.0), "iv": 0.20 + 0.01 * (k - 90)}
            for k in strikes
        ],
        "puts": [
            {"strike": k, "last": max(k - spot, 1.0), "iv": 0.25 + 0.01 * (110 - k)}
            for k in strikes
        ],
    }


class FakeChainService:
    def __init__(self, chain: dict):
        self._chain = chain

    async def get_option_chain(self, symbol: str, **kwargs) -> dict:
        return self._chain


def test_max_pain_picks_symmetric_center() -> None:
    chain = _fake_chain(spot=100.0)
    svc = OptionsSignalsService(market_service=FakeChainService(chain))
    mp = svc._max_pain(100.0, chain["calls"], chain["puts"])
    assert mp == 100.0


def test_interpret_put_bias() -> None:
    bias, strategy, rec = OptionsSignalsService._interpret(100.0, 95.0, 0.05, 1.3, "2026-08-27")
    assert bias == "PUT"
    assert strategy == "bearish"
    assert "PUT" in rec


def test_interpret_call_bias() -> None:
    bias, strategy, _ = OptionsSignalsService._interpret(100.0, 103.0, -0.05, 0.7, "2026-08-27")
    assert bias == "CALL"
    assert strategy == "bullish"


def test_interpret_neutral() -> None:
    bias, strategy, _ = OptionsSignalsService._interpret(100.0, 100.0, 0.01, 1.0, "2026-08-27")
    assert bias == "NEUTRAL"
    assert strategy == "rangebound"


async def test_signals_end_to_end() -> None:
    svc = OptionsSignalsService(market_service=FakeChainService(_fake_chain(spot=100.0)))
    result = await svc.signals("NSE:X")
    assert result["symbol"] == "NSE:X"
    assert result["spot_price"] == 100.0
    assert result["max_pain"] == 100.0
    assert result["premium_put_call"] is not None
    assert result["iv_skew"] is not None
    assert result["bias"] in {"CALL", "PUT", "NEUTRAL"}
    assert result["strategy"] in {"bullish", "bearish", "rangebound"}
    assert result["recommendation"]


# --- Sector analysis ---------------------------------------------------------

class FakeSectorService:
    _QUOTES = {
        "NSE:A": {"price": 100.0, "day_change_pct": 3.0, "sector": "Technology", "market_cap": 1e9},
        "NSE:B": {"price": 200.0, "day_change_pct": 1.0, "sector": "Technology", "market_cap": 5e12},
        "NSE:C": {"price": 300.0, "day_change_pct": -2.0, "sector": "Banking", "market_cap": 2e12},
        "NSE:D": {"price": 400.0, "day_change_pct": 5.0, "sector": "Banking", "market_cap": 4e12},
    }

    async def get_quote(self, symbol: str) -> dict:
        return {**self._QUOTES[symbol], "symbol": symbol, "name": symbol}


def test_cap_class_shared_bands() -> None:
    assert cap_class(1e9, "NSE:X") == "SMALL"
    assert cap_class(2.5e12, "NSE:X") == "LARGE"


async def test_sector_analysis_groups_and_buckets(monkeypatch) -> None:
    from app.services import analysis
    from app.services.data import universe as universe_mod

    svc = SectorAnalysisService(market_service=FakeSectorService())
    symbols = [
        universe_mod.SymbolInfo("NSE:A", "A", "india", "INR"),
        universe_mod.SymbolInfo("NSE:B", "B", "india", "INR"),
        universe_mod.SymbolInfo("NSE:C", "C", "india", "INR"),
        universe_mod.SymbolInfo("NSE:D", "D", "india", "INR"),
    ]
    monkeypatch.setattr(analysis.sectors, "_universe_symbols", lambda market: symbols)
    result = await svc.analyze("india")
    sectors = {s["name"]: s for s in result["sectors"]}
    assert set(sectors) == {"Technology", "Banking"}
    assert sectors["Technology"]["count"] == 2
    assert sectors["Banking"]["avg_change_pct"] == pytest.approx(1.5)
    # Industry grouping inside each sector.
    tech = sectors["Technology"]
    assert tech["industries"]
    assert {i["name"] for i in tech["industries"]} == {"Other"}  # fake quotes carry no industry
    assert sum(i["count"] for i in tech["industries"]) == tech["count"]
    # Cap buckets populated from real market caps.
    caps = result["caps"]
    assert {r["symbol"] for r in caps["SMALL"]} == {"NSE:A"}
    assert {r["symbol"] for r in caps["LARGE"]} == {"NSE:C"}
    assert {r["symbol"] for r in caps["MEGA"]} == {"NSE:B", "NSE:D"}
    # Gainers sorted by change desc.
    assert [r["symbol"] for r in result["top_gainers"]] == ["NSE:D", "NSE:A", "NSE:B"]
