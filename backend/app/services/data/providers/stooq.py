"""Stooq provider (free EOD quotes/history, no API key).

Covers US/global equities and indices; daily/weekly/monthly only (no intraday).
Used as a reliable fallback for US/global lookups when Yahoo is throttled.

Symbol mapping: NYSE/NASDAQ/AMEX/bare -> `TICKER.us`; indices -> `^TICKER`
(e.g. `^spx`). Unsupported exchanges (NSE/BSE/CRYPTO) raise so the fallback
chain moves on.
"""

from __future__ import annotations

import asyncio
import csv
import io
import math
from typing import Any

import httpx

from app.services.data.providers.base import MarketDataProvider, parse_symbol

_BASE = "https://stooq.com"
_SUPPORTED_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", ""}
_INTERVAL_MAP = {"1d": "d", "1w": "w", "1M": "m"}


def _to_stooq(symbol: str) -> str:
    ex, tick = parse_symbol(symbol)
    if ex and ex not in _SUPPORTED_EXCHANGES:
        raise ValueError(f"Stooq does not cover exchange '{ex}'")
    if not tick:
        raise ValueError(f"Empty ticker in '{symbol}'")
    if tick.startswith("^"):
        return tick.lower()
    return f"{tick.lower()}.us"


def _float(value: Any):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _fetch_csv(url: str) -> list[dict[str, str]]:
    """Fetch a CSV payload from stooq with a browser-ish UA + timeout."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    text = resp.text.strip()
    if not text:
        return []
    rows = list(csv.DictReader(io.StringIO(text)))
    # Drop the trailing "no data" pseudo row stooq emits on failures.
    return [r for r in rows if r.get("Close") not in (None, "")]


def _quote_sync(symbol: str) -> dict[str, Any]:
    tick = _to_stooq(symbol)
    url = f"{_BASE}/q/l/?s={tick}&f=sd2t2ohlcv&h&e=csv"
    rows = _fetch_csv(url)
    if not rows:
        raise RuntimeError(f"Stooq returned no quote for {tick}")
    r = rows[0]
    price = _float(r.get("Close"))
    if price is None:
        raise RuntimeError(f"Stooq quote missing price for {tick}")
    prev = _float(r.get("Close", 0))
    open_ = _float(r.get("Open"))
    high = _float(r.get("High"))
    low = _float(r.get("Low"))
    vol = _float(r.get("Volume"))
    change_pct = None
    if prev and prev != price:
        change_pct = (price / prev - 1) * 100
    return {
        "symbol": symbol,
        "name": tick.upper(),
        "price": price,
        "previous_close": prev,
        "open": open_,
        "high": high,
        "low": low,
        "volume": int(vol) if vol is not None else None,
        "currency": "USD",
        "day_change_pct": change_pct,
        "provider": "stooq",
    }


def _history_sync(symbol: str, interval: str, period: str) -> dict[str, Any]:
    tick = _to_stooq(symbol)
    s = _INTERVAL_MAP.get(interval)
    if s is None:
        raise ValueError(f"Stooq does not support interval '{interval}'")
    # Stooq has no look-back periods; pull a generous window and trim to
    # `period` weeks/days to mirror the Yahoo provider contract.
    url = f"{_BASE}/q/d/l/?s={tick}&i={s}"
    rows = _fetch_csv(url)
    if not rows:
        return {"symbol": symbol, "interval": interval, "period": period, "candles": []}
    candles: list[dict[str, Any]] = []
    for r in rows:
        ts = r.get("Date")
        open_ = _float(r.get("Open"))
        high = _float(r.get("High"))
        low = _float(r.get("Low"))
        close = _float(r.get("Close"))
        volume = _float(r.get("Volume"))
        if ts and all(v is not None for v in (open_, high, low, close)):
            candles.append(
                {
                    "ts": f"{ts}",
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": int(volume) if volume is not None else 0,
                }
            )
    limit = _period_to_rows(period)
    if limit:
        candles = candles[-limit:]
    return {"symbol": symbol, "interval": interval, "period": period, "candles": candles}


def _period_to_rows(period: str) -> int | None:
    """Approximate a Yahoo-style period into a row cap for daily series."""
    p = (period or "").lower()
    table = {"1mo": 22, "3mo": 66, "6mo": 132, "1y": 252, "2y": 504, "5y": 1260}
    return table.get(p)


class StooqProvider(MarketDataProvider):
    name = "stooq"
    display_name = "Stooq (free EOD)"

    async def get_quote(self, symbol: str) -> dict:
        return await asyncio.to_thread(_quote_sync, symbol)

    async def get_history(self, symbol: str, *, interval: str = "1d", period: str = "1y") -> dict:
        return await asyncio.to_thread(_history_sync, symbol, interval, period)

    async def get_fundamentals(self, symbol: str) -> dict:
        return {"symbol": symbol, "provider": "stooq", "note": "Fundamentals not available from Stooq."}

    async def health(self) -> bool:
        try:
            await self.get_quote("NYSE:MSFT")
            return True
        except Exception:  # noqa: BLE001
            return False
