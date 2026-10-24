"""Unit tests for the market scanner engine and prediction engine (no network)."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.prediction.engine import PredictionEngine, Timeframe
from app.services.scanners.engine import MarketScanner, ScannerType


def _candles(closes: np.ndarray) -> list[dict]:
    n = len(closes)
    out = []
    for i in range(n):
        out.append(
            {
                "ts": f"2026-01-01T00:00:00",
                "open": float(closes[i]),
                "high": float(closes[i]),
                "low": float(closes[i]),
                "close": float(closes[i]),
                "volume": int(1_000_000 if i == n - 1 else 500_000),
            }
        )
    return out


class FakeMarketService:
    """Deterministic data source: UP trends up, DOWN trends down, FLAT is flat."""

    _SERIES = {
        "NSE:UP": np.linspace(100.0, 130.0, 260),
        "NSE:DOWN": np.linspace(100.0, 70.0, 260),
        "NSE:FLAT": np.full(260, 100.0),
    }

    async def get_quote(self, symbol: str) -> dict:
        change = {"NSE:UP": 2.5, "NSE:DOWN": -2.5, "NSE:FLAT": 0.0}[symbol]
        return {
            "symbol": symbol,
            "name": symbol,
            "price": float(self._SERIES[symbol][-1]),
            "volume": 2_000_000,
            "currency": "INR",
            "day_change_pct": change,
        }

    async def get_history(self, symbol: str, **kwargs) -> dict:
        return {"symbol": symbol, "candles": _candles(self._SERIES[symbol])}

    async def get_fundamentals(self, symbol: str) -> dict:
        if symbol == "NSE:UP":
            return {"trailingPE": 12.0, "priceToBook": 1.2, "returnOnEquity": 0.22,
                    "profitMargins": 0.12, "revenueGrowth": 0.2, "earningsGrowth": 0.25,
                    "dividendYield": 0.02, "debtToEquity": 0.3, "trailingEps": 5.0}
        if symbol == "NSE:DOWN":
            return {"trailingPE": 40.0, "priceToBook": 4.0, "returnOnEquity": 0.02,
                    "profitMargins": 0.01, "revenueGrowth": 0.0, "earningsGrowth": -0.1,
                    "dividendYield": 0.0, "debtToEquity": 1.5, "trailingEps": 1.0}
        return {"trailingPE": 20.0, "priceToBook": 2.5, "returnOnEquity": 0.1,
                "profitMargins": 0.05, "revenueGrowth": 0.0, "earningsGrowth": 0.0,
                "dividendYield": 0.02, "debtToEquity": 0.8, "trailingEps": 2.0}


@pytest.fixture
def scanner() -> MarketScanner:
    return MarketScanner(
        market_service=FakeMarketService(),
        universe=["NSE:UP", "NSE:DOWN", "NSE:FLAT"],
    )


# --- ScannerType resolution ---------------------------------------------------

def test_scanner_type_value_resolution() -> None:
    # The UI sends lowercase values ("52_week_high"); the enum members are named
    # NEW_HIGH/NEW_LOW — value lookup is what the API route now does.
    assert ScannerType("52_week_high") is ScannerType.NEW_HIGH
    assert ScannerType("52_week_low") is ScannerType.NEW_LOW
    assert ScannerType("breakout") is ScannerType.BREAKOUT
    assert ScannerType("options_candidates") is ScannerType.OPTIONS_PLAY


def test_scanner_type_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        ScannerType("not_a_real_scan")


# --- Scanner uses real data, not fabricated ----------------------------------

async def test_new_high_scan_finds_uptrend(scanner: MarketScanner) -> None:
    results = await scanner.scan(ScannerType.NEW_HIGH, market="india", limit=10)
    symbols = [r.symbol for r in results]
    assert "NSE:UP" in symbols
    assert "NSE:DOWN" not in symbols
    up = next(r for r in results if r.symbol == "NSE:UP")
    assert up.price == 130.0
    assert "52-week high" in up.matched_criteria
    assert 0.5 <= up.signal_strength <= 1.0


async def test_new_low_scan_finds_downtrend(scanner: MarketScanner) -> None:
    results = await scanner.scan(ScannerType.NEW_LOW, market="india", limit=10)
    symbols = [r.symbol for r in results]
    assert "NSE:DOWN" in symbols
    assert "NSE:UP" not in symbols


async def test_value_scan_finds_cheap_stock(scanner: MarketScanner) -> None:
    # NSE:UP has the lowest P/E (12), P/B (1.2) and a 2% dividend of the fake
    # set, so it should be the one surfaced by value_picks.
    results = await scanner.scan(ScannerType.VALUE_PICKS, market="india", limit=10)
    symbols = [r.symbol for r in results]
    assert "NSE:UP" in symbols


async def test_scan_never_fabricates_prices(scanner: MarketScanner) -> None:
    # Signal strength and prices come from the fake *data* service, not the
    # engine's own random generator — price must equal the series endpoint.
    results = await scanner.scan(ScannerType.MOMENTUM, market="india", limit=10)
    for r in results:
        assert r.price in (130.0, 70.0, 100.0)


# --- Prediction engine -------------------------------------------------------

@pytest.fixture
def engine() -> PredictionEngine:
    return PredictionEngine(market_service=FakeMarketService())


def test_technical_score_spread(engine: PredictionEngine) -> None:
    up = list(FakeMarketService._SERIES["NSE:UP"])
    down = list(FakeMarketService._SERIES["NSE:DOWN"])
    up_score = engine._calculate_technical_score(up)
    down_score = engine._calculate_technical_score(down)
    assert up_score > 0.6
    assert down_score < 0.4
    assert up_score != down_score


def test_sentiment_score_is_deterministic_and_varies(engine: PredictionEngine) -> None:
    up = list(FakeMarketService._SERIES["NSE:UP"])
    down = list(FakeMarketService._SERIES["NSE:DOWN"])
    assert engine._calculate_sentiment_score(up) == engine._calculate_sentiment_score(up)
    assert engine._calculate_sentiment_score(up) > 0.6
    assert engine._calculate_sentiment_score(down) < 0.4


async def test_predictions_differ_per_symbol(engine: PredictionEngine) -> None:
    up = await engine.predict("NSE:UP", Timeframe.WEEK)
    down = await engine.predict("NSE:DOWN", Timeframe.WEEK)
    assert up.predicted_price > up.current_price
    assert down.predicted_price < down.current_price
    assert up.factors != down.factors
    assert up.factors["sentiment"] != down.factors["sentiment"]
    # Sentiment is never random/hardcoded neutral.
    assert 0.0 < up.factors["sentiment"] < 1.0
    assert 0.0 < down.factors["sentiment"] < 1.0
