"""Batch intraday market board over the curated universe.

Fetches REAL intraday OHLCV for every index and stock in a market (India/US)
and derives an honest live board: last price, day open/high/low, change vs the
previous session's close, day volume and an intraday sparkline — all from the
candle history itself (single data pass per symbol, no fabricated rows). A
symbol that fails to return candles is reported with its error, never dropped
silently.

Day boundaries are taken from the candle timestamps (the provider's session
day, e.g. the last day group in the window is "today"). ``change_pct`` is
computed against the close of the previous session in the window, falling back
to the day's open when no prior session exists.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.services.data.service import MarketDataService, market_data
from app.services.data.universe import by_market

logger = get_logger("analysis.intraday")

# yfinance caps how far back an intraday interval can go; clamp server-side so a
# 1m/5d request never 404s — mirror of the frontend INTERVAL_PERIOD_LIMIT.
INTERVAL_PERIOD_LIMIT: dict[str, str] = {
    "1m": "5d",
    "5m": "1mo",
    "15m": "1mo",
    "1h": "1y",
}
_PERIOD_ORDER = ["5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"]


def clamp_period(interval: str, period: str) -> str:
    cap = INTERVAL_PERIOD_LIMIT.get(interval)
    if not cap:
        return period
    try:
        if _PERIOD_ORDER.index(period) > _PERIOD_ORDER.index(cap):
            return cap
    except ValueError:
        return cap
    return period


def _day_key(ts: str) -> str:
    return (ts or "")[:10]


class IntradayBoard:
    """Builds a real intraday board for a whole market in one batched pass."""

    def __init__(self, market_service: MarketDataService | None = None) -> None:
        self.market_service = market_service or market_data

    async def board(
        self,
        market: str = "india",
        interval: str = "1m",
        period: str = "5d",
        limit: int = 90,
        concurrency: int = 8,
    ) -> dict:
        symbols = by_market(market)
        if not symbols:
            return {"market": market, "interval": interval, "period": period,
                    "generated_at": None, "rows": [], "total": 0, "errors": 0}
        period = clamp_period(interval, period)
        sem = asyncio.Semaphore(concurrency)

        async def one(info: dict) -> dict:
            symbol = info["symbol"]
            async with sem:
                try:
                    history = await self.market_service.get_history_auto(
                        symbol, interval=interval, period=period
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("intraday %s failed: %s", symbol, exc)
                    return self._row(info, None, error=str(exc))
            candles = (history or {}).get("candles") or []
            if not candles:
                return self._row(info, None, error=(history or {}).get("error") or "no candles")
            derived = self._derive(candles)
            return self._row(info, derived, source=(history or {}).get("source"))

        rows = await asyncio.gather(*(one(s) for s in symbols[:limit]))
        rows = [r for r in rows if r]
        ok = [r for r in rows if r.get("last") is not None]
        err = [r for r in rows if r.get("last") is None]
        # Indices first, then by strength of the day's move.
        ok.sort(key=lambda r: (not r.get("index"), -abs(r.get("change_pct") or 0)))
        return {
            "market": market,
            "interval": interval,
            "period": period,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rows": ok + err,
            "total": len(rows),
            "errors": len(err),
        }

    @staticmethod
    def _derive(candles: list[dict]) -> dict | None:
        """Derive the live day board from intraday candles (single data pass)."""
        by_day: dict[str, list[dict]] = {}
        for c in candles:
            by_day.setdefault(_day_key(str(c.get("ts") or "")), []).append(c)
        if not by_day:
            return None
        today_key = max(by_day)
        today = by_day[today_key]
        last = float(today[-1]["close"])
        day_open = float(today[0]["open"])
        high = max(float(c["high"]) for c in today)
        low = min(float(c["low"]) for c in today)
        vol = sum(float(c.get("volume") or 0) for c in today)

        prev_keys = [k for k in by_day if k < today_key]
        prev_close = float(by_day[prev_keys[-1]][-1]["close"]) if prev_keys else day_open
        change = last - prev_close
        change_pct = (change / prev_close * 100.0) if prev_close else None
        sparkline = [float(c["close"]) for c in today]
        return {
            "last": last,
            "prev_close": prev_close,
            "day_open": day_open,
            "high": high,
            "low": low,
            "change": change,
            "change_pct": change_pct,
            "day_volume": vol,
            "sparkline": sparkline[-150:],
            "bars": len(today),
        }

    @staticmethod
    def _row(info: dict, derived: dict | None, *, source: str | None = None, error: str | None = None) -> dict:
        row = {
            "symbol": info["symbol"],
            "name": info.get("name") or info["symbol"],
            "market": info.get("market") or "india",
            "currency": info.get("currency"),
            "index": bool(info.get("index")),
            "source": source,
            "error": None,
        }
        if derived:
            row.update(derived)
        else:
            row.update({"last": None, "prev_close": None, "day_open": None, "high": None,
                        "low": None, "change": None, "change_pct": None, "day_volume": None,
                        "sparkline": [], "bars": 0})
        if error:
            row["error"] = error
        return row


intraday_board_service = IntradayBoard()