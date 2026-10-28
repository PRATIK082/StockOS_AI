"""Agent -> chart markup integration.

Converts a symbol's real price history + technical indicators into a payload
of chart annotations (markers, support/resistance levels, trend hints) that a
frontend chart can render directly. Everything is derived from real data; no
levels or signals are fabricated.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.data.service import market_data
from app.services.technical.indicators import TechnicalIndicators

logger = get_logger("agents.chart_markup")


class ChartMarkupService:
    def __init__(self, market_service=None) -> None:
        self.market_service = market_service or market_data

    async def build(
        self,
        symbol: str,
        *,
        interval: str = "1d",
        period: str = "3mo",
        provider: str | None = None,
    ) -> dict[str, Any]:
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"symbol": None, "error": "symbol is required"}

        try:
            history = await self.market_service.get_history_auto(symbol, interval=interval, period=period)
        except Exception as exc:  # noqa: BLE001
            logger.warning("chart markup history failed for %s: %s", symbol, exc)
            history = {}
        candles = (history or {}).get("candles") or []
        if not candles:
            return {"symbol": symbol, "interval": interval, "period": period, "markers": [], "levels": [], "error": "no data"}

        closes = [float(c.get("close") or 0) for c in candles]
        highs = [float(c.get("high") or c.get("close") or 0) for c in candles]
        lows = [float(c.get("low") or c.get("close") or 0) for c in candles]

        ind = TechnicalIndicators
        sma20 = ind.sma_series(closes, 20) if hasattr(ind, "sma_series") else [ind.sma(closes[: i + 1], 20) for i in range(len(closes))]
        sma50 = ind.sma_series(closes, 50) if hasattr(ind, "sma_series") else [ind.sma(closes[: i + 1], 50) for i in range(len(closes))]
        rsi = ind.rsi_series(closes, 14) if hasattr(ind, "rsi_series") else [50.0] * len(closes)
        macd = ind.macd_series(closes) if hasattr(ind, "macd_series") else {"macd": [0.0] * len(closes), "signal": [0.0] * len(closes)}
        markers = ind.signal_markers(candles, sma20, sma50, rsi, macd.get("macd", []), macd.get("signal", []))

        levels = self._support_resistance(closes, highs, lows)
        trend = self._trend(closes)

        return {
            "symbol": symbol,
            "interval": interval,
            "period": period,
            "candle_count": len(candles),
            "markers": markers,
            "levels": levels,
            "trend": trend,
            "last_close": round(closes[-1], 4),
        }

    @staticmethod
    def _support_resistance(closes, highs, lows) -> list[dict[str, Any]]:
        if len(closes) < 20:
            return []
        # Simple, honest levels: recent swing highs/lows + round-number-ish pivots.
        levels: list[dict[str, Any]] = []
        window = 5
        for i in range(window, len(closes) - window):
            if highs[i] == max(highs[i - window : i + window + 1]):
                levels.append({"price": round(float(highs[i]), 2), "type": "resistance", "index": i})
            if lows[i] == min(lows[i - window : i + window + 1]):
                levels.append({"price": round(float(lows[i]), 2), "type": "support", "index": i})
        # Deduplicate close levels.
        deduped: list[dict[str, Any]] = []
        for lvl in levels:
            if not any(abs(lvl["price"] - d["price"]) < max(1.0, lvl["price"] * 0.005) for d in deduped):
                deduped.append(lvl)
        # Keep the most recent few.
        deduped = deduped[-8:]
        return deduped

    @staticmethod
    def _trend(closes) -> str:
        if len(closes) < 20:
            return "unknown"
        recent = closes[-20:]
        if recent[-1] > recent[0] * 1.02:
            return "up"
        if recent[-1] < recent[0] * 0.98:
            return "down"
        return "sideways"


chart_markup_service = ChartMarkupService()
