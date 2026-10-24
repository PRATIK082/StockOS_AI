"""TradingView provider (free) — the source of real NSE/BSE options chains.

NSE's own option-chain endpoints are hard-blocked for automated access (Akamai
403), and Yahoo does not list Indian derivatives, so NSE/BSE chains used to 404.
TradingView's options scanner (`scanner.tradingview.com/options/scan2`) returns
the full chain for any Indian underlying: expiries, strikes, IV, full Greeks and
a theoretical price (`theoPrice`) in one HTTP call.

What it provides / does not provide:
- Available: expiries, strikes, option type, IV (incl. bid/ask IV), delta,
  gamma, theta, vega, rho, theoretical price, currency.
- NOT available from the scanner: live bid/ask, last trade, volume and open
  interest (those columns are not returned for options). Those fields are left
  empty/zero rather than fabricated, so max pain / PCR degrade gracefully and
  strategies price legs off `theoPrice`.
- Underlying spot is fetched from the Yahoo provider (NSE/BSE equities + index
  symbols); if that fails it falls back to the ATM strike derived from IV.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.data.providers.base import MarketDataProvider, OptionsUnavailableError, parse_symbol

logger = get_logger("data.tradingview")

_SCAN_URL = "https://scanner.tradingview.com/options/scan2?label-product=symbols-options"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "Accept": "application/json, text/plain, */*",
}

# Columns the options scanner supports (structure + IV + Greeks + theo price).
_SCAN_COLUMNS = [
    "name", "root", "currency", "expiration", "strike", "option-type",
    "theoPrice", "iv", "delta", "gamma", "theta", "vega", "rho",
]

# NSE/BSE index tickers whose Yahoo symbol is an index (no `.NS`/`.BO` suffix).
_INDEX_YAHOO = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYBANK": "^NSEBANK",
    "SENSEX": "^BSESN",
    "BSESENSEX": "^BSESN",
}

_SUPPORTED_EXCHANGES = {"NSE", "BSE", "NSEFO", "BSEFO"}
_EXCHANGE_ALIAS = {"NSEFO": "NSE", "BSEFO": "BSE"}

# Correct underlying symbol on TradingView when the platform's own namespace
# differs (e.g. SENSEX is listed under BSE, not NSE).
_SYMBOL_ALIAS = {"NSE:SENSEX": "BSE:SENSEX"}


def _num(value: Any) -> float:
    """Coerce a scanner value to a finite float, defaulting to 0.0."""
    try:
        v = float(value)
        return v if v == v else 0.0
    except (TypeError, ValueError):
        return 0.0


class TradingViewProvider(MarketDataProvider):
    name = "tradingview"
    display_name = "TradingView (India options)"

    # --- quotes / history / fundamentals -----------------------------------
    # TradingView's option scanner is used only for chains; quotes, history and
    # fundamentals for NSE/BSE symbols keep flowing through the Yahoo provider
    # (which covers `.NS`/`.BO` and Indian index symbols), so routing NSE/BSE to
    # this provider is a drop-in for the whole data surface.

    @staticmethod
    def _to_yahoo_symbol(symbol: str) -> str:
        """Map an index ticker (NIFTY/BANKNIFTY/SENSEX) to its Yahoo symbol."""
        _ex, tick = parse_symbol(symbol)
        return _INDEX_YAHOO.get(tick, symbol)

    async def get_quote(self, symbol: str) -> dict:
        from app.services.data.providers.yahoo import YahooProvider

        return await YahooProvider().get_quote(self._to_yahoo_symbol(symbol))

    async def get_history(self, symbol: str, *, interval: str = "1d", period: str = "1y") -> dict:
        from app.services.data.providers.yahoo import YahooProvider

        return await YahooProvider().get_history(
            self._to_yahoo_symbol(symbol), interval=interval, period=period
        )

    async def get_fundamentals(self, symbol: str) -> dict:
        from app.services.data.providers.yahoo import YahooProvider

        return await YahooProvider().get_fundamentals(self._to_yahoo_symbol(symbol))

    # --- options chain ------------------------------------------------------

    async def get_option_chain(self, symbol: str, *, expiry: str | None = None) -> dict:
        ex, tick = parse_symbol(symbol)
        if ex not in _SUPPORTED_EXCHANGES:
            raise OptionsUnavailableError(
                f"TradingView's options feed covers NSE/BSE derivatives only; '{symbol}' has no "
                "Indian option chain here. Try NSE:NIFTY, NSE:BANKNIFTY, or NSE:TCS."
            )
        underlying = _SYMBOL_ALIAS.get(f"{_EXCHANGE_ALIAS.get(ex, ex)}:{tick}", f"{_EXCHANGE_ALIAS.get(ex, ex)}:{tick}")

        try:
            expiries_raw = await self._fetch_scan(underlying, columns=["expiration"])
        except httpx.HTTPError as exc:
            raise OptionsUnavailableError(
                f"TradingView options feed unreachable for {underlying}: {exc}"
            ) from exc

        expiries = sorted(
            {self._to_iso(row.get("expiration")) for row in expiries_raw
             if row.get("expiration") is not None}
        )
        if not expiries:
            raise OptionsUnavailableError(f"No options listings available for {underlying}")

        chosen = self._pick_expiry(expiries, expiry)
        legs_raw = await self._fetch_scan(
            underlying, columns=_SCAN_COLUMNS, expiry=int(chosen.replace("-", ""))
        )

        calls: list[dict] = []
        puts: list[dict] = []
        for row in legs_raw:
            leg = self._leg(row)
            if leg is None:
                continue
            (calls if row.get("option-type") == "call" else puts).append(leg)
        if not calls and not puts:
            raise OptionsUnavailableError(
                f"No option rows returned for {underlying} at expiry {chosen}"
            )

        spot = await self._spot_price(underlying, calls, puts)
        return {
            "symbol": underlying,
            "expiry": chosen,
            "expiries": expiries,
            "spot_price": spot,
            "calls": calls,
            "puts": puts,
            "provider": self.name,
        }

    async def health(self) -> bool:
        try:
            rows = await self._fetch_scan("NSE:NIFTY", columns=["expiration"])
            return bool(rows)
        except Exception:  # noqa: BLE001
            return False

    # --- internals ----------------------------------------------------------

    @staticmethod
    def _to_iso(value: Any) -> str | None:
        """Normalize an `expiration` value (e.g. 20260825) to `YYYY-MM-DD`."""
        if value is None:
            return None
        s = str(value).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        return s[:10]

    @staticmethod
    def _pick_expiry(expiries: list[str], requested: str | None) -> str:
        """Resolve the requested expiry (or the next upcoming one).

        A requested date that is not listed is resolved to the closest listed
        expiry instead of failing, so stale saved dates still load a real chain.
        """
        if requested:
            want = requested.strip()[:10]
            if want in expiries:
                return want
            near = min(expiries, key=lambda e: abs(
                (date.fromisoformat(e) - date.fromisoformat(want)).days
            ))
            logger.debug(
                "expiry %s not listed for symbol, using nearest listed %s "
                "(available: %s)", want, near, expiries
            )
            return near
        today = date.today().isoformat()
        upcoming = [e for e in expiries if e >= today]
        return min(upcoming) if upcoming else min(expiries)

    @staticmethod
    def _leg(row: dict) -> dict | None:
        strike = row.get("strike")
        opt_type = row.get("option-type")
        if strike is None or opt_type not in {"call", "put"}:
            return None
        return {
            "strike": float(strike),
            # No live bid/ask/OI/volume from the scanner — left honest.
            "bid": None,
            "ask": None,
            "last": _num(row.get("theoPrice")),
            "volume": 0,
            "oi": 0,
            "iv": _num(row.get("iv")),
            "delta": _num(row.get("delta")),
            "gamma": _num(row.get("gamma")),
            "theta": _num(row.get("theta")),
            "vega": _num(row.get("vega")),
            "rho": _num(row.get("rho")),
        }

    async def _spot_price(self, underlying: str, calls: list[dict], puts: list[dict]) -> float:
        """Underlying spot from Yahoo; falls back to the ATM strike via IV."""
        try:
            from app.services.data.providers.yahoo import YahooProvider

            quote_symbol = self._to_yahoo_symbol(underlying)
            quote = await YahooProvider().get_quote(quote_symbol)
            price = quote.get("price")
            if price:
                return float(price)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Spot quote failed for %s (using ATM strike): %s", underlying, exc)
        return self._atm_strike(calls, puts)

    @staticmethod
    def _atm_strike(calls: list[dict], puts: list[dict]) -> float:
        """Strike whose combined call+put IV is smallest ≈ at-the-money."""
        call_map = {float(r["strike"]): r for r in calls}
        put_map = {float(r["strike"]): r for r in puts}
        best_k, best_iv = None, float("inf")
        for k, call in call_map.items():
            put = put_map.get(k)
            if put is not None:
                iv = call["iv"] + put["iv"]
                if iv < best_iv:
                    best_iv, best_k = iv, k
        if best_k is not None:
            return best_k
        keys = sorted(call_map) or sorted(put_map)
        return float(keys[len(keys) // 2]) if keys else 0.0

    async def _fetch_scan(
        self, underlying: str, *, columns: list[str], expiry: int | None = None
    ) -> list[dict]:
        """Query TradingView's options scanner; rows mapped column-name → value."""
        flt = [{"left": "type", "operation": "equal", "right": "option"}]
        if expiry is not None:
            flt.append({"left": "expiration", "operation": "equal", "right": int(expiry)})
        body = {
            "columns": columns,
            "filter": flt,
            "index_filters": [{"name": "underlying_symbol", "values": [underlying]}],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_SCAN_URL, json=body, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
        return [dict(zip(columns, item.get("f") or [])) for item in data.get("symbols") or []]
