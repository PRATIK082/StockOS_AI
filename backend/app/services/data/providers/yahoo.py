"""Yahoo Finance provider (free). Uses the `yfinance` package.

Maps exchange namespaces to yfinance suffixes: NSE->`.NS`, BSE/BOM->`.BO`,
bare or US exchanges (NYSE/NASDAQ/AMEX) are used as-is.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Callable

from app.services.data.providers.base import MarketDataProvider, OptionsUnavailableError, parse_symbol

_NS_MAP = {
    "NSE": ".NS",
    "BSE": ".BO",
    "BOM": ".BO",
}
_PASS_THROUGH = {"NYSE", "NASDAQ", "AMEX"}


def _to_yfinance(symbol: str) -> str:
    ex, tick = parse_symbol(symbol)
    if ex in _NS_MAP:
        return f"{tick}{_NS_MAP[ex]}"
    return tick


def _num(item: Any, key: str):
    try:
        v = item.get(key)
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return round(float(v), 6)
        return None
    except (TypeError, ValueError):
        return None


def _is_empty(result: Any) -> bool:
    """True when a result carries no data (list/dict/str or a pandas object)."""
    if result is None:
        return True
    if hasattr(result, "empty"):  # pandas Series/DataFrame
        return bool(result.empty)
    if isinstance(result, (list, dict, tuple, str)):
        return not result
    return False


def _retry(call: Callable[[], Any], *, attempts: int = 3, delay: float = 1.0, empty_ok: bool = False):
    """Run `call`, retrying on exceptions (and empty results when requested).

    yfinance's free feed throttles aggressively under load; a single empty
    response is normal. Retrying with backoff turns most transient failures
    into real data instead of 404s for downstream consumers.
    """
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            result = call()
            if empty_ok and _is_empty(result):
                raise RuntimeError("yfinance returned an empty result (rate-limited?)")
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(delay * (i + 1))
    raise last_exc or RuntimeError("retry exhausted")


def _quote_sync(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    info: dict[str, Any] = {}
    try:
        info = _retry(lambda: t.info or {}, empty_ok=True) or {}
    except Exception:  # noqa: BLE001
        info = {}
    # Fall back to recent candles when `info` 404s (Yahoo quirks for some
    # symbols) so quotes keep working with real prices.
    hist = None
    try:
        hist = _retry(lambda: t.history(period="5d", interval="1d"), empty_ok=True)
    except Exception:  # noqa: BLE001
        hist = None
    last = hist.iloc[-1] if hist is not None and not hist.empty else {}
    prev = hist.iloc[-2] if hist is not None and len(hist) > 1 else {}
    price = info.get("regularMarketPrice") or _num(last, "Close")
    prev_close = info.get("regularMarketPreviousClose") or _num(prev, "Close")
    change_pct = info.get("regularMarketChangePercent")
    if change_pct is None and isinstance(price, (int, float)) and isinstance(prev_close, (int, float)) and prev_close:
        change_pct = (price / prev_close - 1) * 100
    return {
        "symbol": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "price": price,
        "previous_close": prev_close,
        "open": info.get("regularMarketOpen") or _num(last, "Open"),
        "high": info.get("regularMarketDayHigh") or _num(last, "High"),
        "low": info.get("regularMarketDayLow") or _num(last, "Low"),
        "volume": info.get("regularMarketVolume") or _num(last, "Volume"),
        "currency": info.get("currency", "USD"),
        "day_change_pct": change_pct,
        "market_cap": info.get("marketCap"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "provider": "yahoo",
    }


def _history_sync(ticker: str, interval: str, period: str) -> dict[str, Any]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    hist = _retry(
        lambda: t.history(period=period, interval=interval),
        empty_ok=True,
    )
    candles = []
    for idx, row in hist.iterrows():
        open_ = _num(row, "Open")
        high = _num(row, "High")
        low = _num(row, "Low")
        close = _num(row, "Close")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (open_, high, low, close)):
            # yfinance returns an incomplete last bar (NaN OHLC); drop it
            # rather than serving garbage that charts cannot render.
            continue
        volume = _num(row, "Volume")
        if volume is not None and isinstance(volume, (int, float)) and math.isfinite(volume):
            volume = int(volume)
        else:
            volume = 0
        candles.append(
            {
                "ts": idx.isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": int(volume),
            }
        )
    return {"symbol": ticker, "interval": interval, "period": period, "candles": candles}


def _finite_num(value, default: float = 0.0) -> float:
    """Coerce to a finite number, falling back to `default`."""
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _option_row(row) -> dict:
    """Normalize a yfinance option row to the platform option shape."""
    return {
        "strike": _finite_num(row.get("strike")),
        "bid": _finite_num(row.get("bid")),
        "ask": _finite_num(row.get("ask")),
        "last": _finite_num(row.get("lastPrice")),
        "volume": int(_finite_num(row.get("volume"))),
        "oi": int(_finite_num(row.get("openInterest"))),
        "iv": _finite_num(row.get("impliedVolatility")),
    }


def _option_chain_sync(ticker: str, expiry: str | None) -> dict:
    import yfinance as yf

    t = yf.Ticker(ticker)
    dates = t.options or ()
    if not dates:
        raise OptionsUnavailableError(f"No options listings available for {ticker}")
    chosen = (expiry or "")[:10] or dates[0]
    if chosen not in dates:
        raise OptionsUnavailableError(f"Expiry {chosen} not available for {ticker}")
    oc = t.option_chain(chosen)
    spot = None
    try:
        spot = _num({"lastPrice": t.fast_info["lastPrice"]}, "lastPrice")
    except Exception:  # noqa: BLE001
        spot = None
    if spot is None:
        spot = _quote_sync(ticker).get("price")
    return {
        "symbol": ticker,
        "expiry": chosen,
        "expiries": list(dates),
        "spot_price": spot,
        "calls": [_option_row(r) for _, r in oc.calls.iterrows()],
        "puts": [_option_row(r) for _, r in oc.puts.iterrows()],
        "provider": "yahoo",
    }


def _fundamentals_sync(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    info = _retry(lambda: t.info or {}, empty_ok=True) or {}
    numeric_keys = [
        "trailingPE", "forwardPE", "priceToBook", "returnOnEquity", "returnOnAssets",
        "debtToEquity", "profitMargins", "operatingMargins", "revenueGrowth",
        "earningsGrowth", "dividendYield", "totalCash", "totalDebt", "freeCashflow",
        "marketCap", "bookValue", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "beta",
        "trailingEps", "sharesOutstanding",
    ]
    string_keys = ["sector", "industry", "longName", "shortName"]
    out = {"symbol": ticker, "provider": "yahoo"}
    for k in numeric_keys:
        out[k] = _num(info, k)
    for k in string_keys:
        out[k] = info.get(k) if isinstance(info.get(k), str) else None
    return out


class YahooProvider(MarketDataProvider):
    name = "yahoo"
    display_name = "Yahoo Finance"

    async def get_quote(self, symbol: str) -> dict:
        return await asyncio.to_thread(_quote_sync, _to_yfinance(symbol))

    async def get_history(self, symbol: str, *, interval: str = "1d", period: str = "1y") -> dict:
        return await asyncio.to_thread(_history_sync, _to_yfinance(symbol), interval, period)

    async def get_fundamentals(self, symbol: str) -> dict:
        return await asyncio.to_thread(_fundamentals_sync, _to_yfinance(symbol))

    async def get_option_chain(self, symbol: str, *, expiry: str | None = None) -> dict:
        return await asyncio.to_thread(_option_chain_sync, _to_yfinance(symbol), expiry)