"""Binance crypto provider (free public API, no API key).

Covers spot and USDT-margined perpetual pairs, e.g. `BINANCE:BTCUSDT`,
`CRYPTO:ETHUSDT` or a bare pair like `BTCUSDT`. Symbols carrying a slash
(`BTC/USDT`) or a `-PERP` suffix are normalized to the Binance pair format.
Intraday + daily bars; quotes from the 24h ticker. Fundamentals are empty
(honest degradation).
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx

from app.services.data.providers.base import MarketDataProvider, parse_symbol

_BASE = "https://api.binance.com"
_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w", "1M": "1M",
}
_MAX_KLINE_LIMIT = 1000

_CRYPTO_EXCHANGES = {"BINANCE", "CRYPTO", "BYBIT", "OKX", "COINBASE"}


def _normalize(symbol: str) -> str:
    ex, tick = parse_symbol(symbol)
    if ex and ex not in _CRYPTO_EXCHANGES:
        raise ValueError(f"Binance does not cover exchange '{ex}'")
    tick = (tick or symbol).strip().upper()
    tick = tick.replace("/", "")
    if tick.endswith("-PERP"):
        tick = tick[:-5] + "USDT"
    if not tick.endswith("USDT") and tick.isalpha():
        tick = f"{tick}USDT"
    if not tick:
        raise ValueError(f"Empty crypto symbol '{symbol}'")
    return tick


def _float(value: Any):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _get_json(url: str) -> Any:
    resp = httpx.get(url, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def _quote_sync(symbol: str) -> dict[str, Any]:
    tick = _normalize(symbol)
    data = _get_json(f"{_BASE}/api/v3/ticker/24hr?symbol={tick}")
    price = _float(data.get("lastPrice"))
    if price is None:
        raise RuntimeError(f"Binance returned no price for {tick}")
    return {
        "symbol": symbol,
        "name": tick,
        "price": price,
        "previous_close": _float(data.get("prevClosePrice")),
        "open": _float(data.get("openPrice")),
        "high": _float(data.get("highPrice")),
        "low": _float(data.get("lowPrice")),
        "volume": _int(data.get("quoteVolume")),
        "currency": "USDT",
        "day_change_pct": _float(data.get("priceChangePercent")),
        "provider": "crypto",
    }


def _history_sync(symbol: str, interval: str, period: str) -> dict[str, Any]:
    tick = _normalize(symbol)
    k = _INTERVAL_MAP.get(interval)
    if k is None:
        raise ValueError(f"Binance does not support interval '{interval}'")
    limit = _max_bars(period)
    params = f"symbol={tick}&interval={k}&limit={limit}"
    data = _get_json(f"{_BASE}/api/v3/klines?{params}")
    candles: list[dict[str, Any]] = []
    for row in data or []:
        open_ = _float(row[1])
        high = _float(row[2])
        low = _float(row[3])
        close = _float(row[4])
        if all(v is not None for v in (open_, high, low, close)):
            candles.append(
                {
                    "ts": _kline_ts(row[0]),
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": _int(row[5]),
                }
            )
    return {"symbol": symbol, "interval": interval, "period": period, "candles": candles}


def _kline_ts(ms: Any) -> str:
    """Kline open-time ms -> UTC ISO (defensive against non-int payloads)."""
    import datetime as _dt

    try:
        return _dt.datetime.fromtimestamp(int(ms) / 1000, tz=_dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(ms)


def _max_bars(period: str) -> int:
    p = (period or "").lower()
    table = {"1d": 2, "5d": 6, "1mo": 31, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1000}
    return min(max(table.get(p, 365), 30), _MAX_KLINE_LIMIT)


class CryptoProvider(MarketDataProvider):
    name = "crypto"
    display_name = "Binance (crypto)"

    async def get_quote(self, symbol: str) -> dict:
        return await asyncio.to_thread(_quote_sync, symbol)

    async def get_history(self, symbol: str, *, interval: str = "1d", period: str = "1y") -> dict:
        return await asyncio.to_thread(_history_sync, symbol, interval, period)

    async def get_fundamentals(self, symbol: str) -> dict:
        return {"symbol": symbol, "provider": "crypto", "note": "Fundamentals not available for crypto."}

    async def health(self) -> bool:
        try:
            await self.get_quote("CRYPTO:BTCUSDT")
            return True
        except Exception:  # noqa: BLE001
            return False
