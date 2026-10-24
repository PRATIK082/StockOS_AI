"""NSE India provider (free public endpoints).

Fetches quotes from NSE's public JSON APIs. These endpoints can change and
require browser-like headers; failures are surfaced to the caller rather than
masked.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.data.providers.base import MarketDataProvider, OptionsUnavailableError, parse_symbol

logger = get_logger("data.nse")

NSE_BASE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


class NSEProvider(MarketDataProvider):
    name = "nse"
    display_name = "NSE India"

    async def get_quote(self, symbol: str) -> dict:
        _ex, tick = parse_symbol(symbol)
        url = f"{NSE_BASE}/api/quote-equity?symbol={tick}"
        data = await self._get_json(url)
        info = data.get("priceInfo", {}) or {}
        return {
            "symbol": f"NSE:{tick}",
            "name": data.get("companyName") or tick,
            "price": info.get("lastPrice"),
            "previous_close": info.get("previousClose"),
            "open": info.get("open"),
            "high": info.get("intraDayHighLow", {}).get("max") or info.get("high"),
            "low": info.get("intraDayHighLow", {}).get("min") or info.get("low"),
            "volume": info.get("totalTradedVolume"),
            "currency": "INR",
            "day_change_pct": info.get("pChange"),
            "market_cap": (data.get("securityInfo") or {}).get("marketCap"),
            "sector": None,
            "provider": "nse",
        }

    async def get_history(self, symbol: str, *, interval: str = "1d", period: str = "1y") -> dict:
        # NSE's public API has no free historical endpoint. Delegate to the
        # Yahoo provider (which covers NSE symbols via the `.NS` suffix) so
        # charts still work while preserving NSE for quote/fundamentals.
        from app.services.data.providers.yahoo import YahooProvider

        logger.info("NSE history unavailable as a free feed; using Yahoo for %s", symbol)
        return await YahooProvider().get_history(symbol, interval=interval, period=period)

    async def get_fundamentals(self, symbol: str) -> dict:
        _sym, tick = parse_symbol(symbol)
        return {"symbol": f"NSE:{tick}", "provider": "nse"}

    async def get_option_chain(self, symbol: str, *, expiry: str | None = None) -> dict:
        """Fetch a real NSE options chain (equity or index).

        NSE has no free historical/option API for automated clients and returns
        403/404 to scripts; failures are surfaced as `OptionsUnavailableError`
        so callers can report a clear message instead of fake data.
        """
        ex, tick = parse_symbol(symbol)
        is_index = ex in {"NSEFO", "BSEFO"} or tick in {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "NIFTYNXT50"}
        endpoint = "option-chain-indices" if is_index else "option-chain-equities"
        url = f"{NSE_BASE}/api/{endpoint}?symbol={tick}"
        try:
            data = await self._get_json(url)
        except Exception as exc:  # noqa: BLE001
            raise OptionsUnavailableError(
                f"NSE options feed is blocked for automated access ({endpoint} {tick}: {exc}). "
                "Try a US symbol (e.g. NYSE:AAPL) where a real free options feed is available."
            ) from exc

        records = (data.get("data") or {}).get("records") or {}
        rows = records.get("data") or []
        if not rows:
            raise OptionsUnavailableError(f"No options data returned for NSE:{tick}")

        def leg(row: dict) -> dict | None:
            if not row:
                return None
            return {
                "strike": row.get("strikePrice"),
                "bid": row.get("bidprice") or row.get("bidPrice"),
                "ask": row.get("askPrice") or row.get("askprice"),
                "last": row.get("lastPrice"),
                "volume": row.get("totalTradedVolume") or 0,
                "oi": row.get("openInterest") or 0,
                "iv": row.get("impliedVolatility") or 0.0,
            }

        calls = [c for r in rows if (c := leg(r.get("CE"))) is not None]
        puts = [p for r in rows if (p := leg(r.get("PE"))) is not None]

        dates = records.get("expiryDates") or []
        chosen = expiry or (dates[0] if dates else None)
        return {
            "symbol": f"NSE:{tick}",
            "expiry": chosen,
            "spot_price": records.get("underlyingValue"),
            "calls": calls,
            "puts": puts,
            "provider": "nse",
        }

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{NSE_BASE}/api/allIndices", headers=_HEADERS)
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def _get_json(self, url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # Prime the session with a homepage hit so NSE serves the API cookie.
            await client.get(NSE_BASE, headers=_HEADERS)
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
            return resp.json()