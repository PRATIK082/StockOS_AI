"""Market Data Service.

Registry + facade over data providers. The caller can select a provider per
request (e.g. `?provider=nse`); the configured default is used otherwise. If an
exchange-specific provider fails (e.g. NSE blocks automated access), it falls
back to the Yahoo provider so lookups still work. New paid providers (Polygon,
Finnhub, Alpha Vantage, TwelveData) simply implement `MarketDataProvider` and
register here.
"""

from __future__ import annotations

import time

from app.core.config import settings
from app.core.logging import get_logger
from app.services.data.providers import (
    CryptoProvider,
    LocalProvider,
    MarketDataProvider,
    NSEProvider,
    StooqProvider,
    TradingViewProvider,
    YahooProvider,
)

logger = get_logger("data.service")

PROVIDERS: dict[str, MarketDataProvider] = {
    "yahoo": YahooProvider(),
    "nse": NSEProvider(),
    "tradingview": TradingViewProvider(),
    "stooq": StooqProvider(),
    "crypto": CryptoProvider(),
    "local": LocalProvider(),
}

# Map of exchange -> preferred provider for sensible defaults.
EXCHANGE_PROVIDER = {
    "NSE": "tradingview",
    "BSE": "tradingview",
    "BOM": "tradingview",
    "NSEFO": "tradingview",
    "BSEFO": "tradingview",
    "NYSE": "yahoo",
    "NASDAQ": "yahoo",
    "AMEX": "yahoo",
    "BINANCE": "crypto",
    "CRYPTO": "crypto",
    "LOCAL": "local",
}

# Human-readable capability metadata surfaced by the health readout so the UI
# can tell users honestly which provider serves which data.
PROVIDER_META: dict[str, dict] = {
    "yahoo": {
        "display_name": "Yahoo Finance",
        "exchanges": ["NYSE", "NASDAQ", "AMEX", "NSE", "BSE"],
        "capabilities": ["quote", "history", "fundamentals"],
        "notes": "Default for US markets; used as the universal fallback.",
    },
    "tradingview": {
        "display_name": "TradingView (India options)",
        "exchanges": ["NSE", "BSE", "NSEFO", "BSEFO"],
        "capabilities": ["quote", "history", "fundamentals", "options_chain"],
        "notes": "Real Indian options chains; delegates quotes/history/fundamentals to Yahoo.",
    },
    "nse": {
        "display_name": "NSE India",
        "exchanges": ["NSE"],
        "capabilities": ["options_chain"],
        "notes": "NSE public API blocks automated access; use tradingview/yahoo instead.",
    },
    "stooq": {
        "display_name": "Stooq (free EOD)",
        "exchanges": ["NYSE", "NASDAQ", "AMEX"],
        "capabilities": ["quote", "history"],
        "notes": "Keyless EOD fallback for US/global symbols; daily/weekly/monthly only.",
    },
    "crypto": {
        "display_name": "Binance (crypto)",
        "exchanges": ["BINANCE", "CRYPTO"],
        "capabilities": ["quote", "history"],
        "notes": "Keyless Binance public API for spot/perpetual pairs (e.g. BTCUSDT).",
    },
    "local": {
        "display_name": "Local files (CSV/Parquet)",
        "exchanges": ["LOCAL"],
        "capabilities": ["quote", "history"],
        "notes": "Bring-your-own OHLCV from the configured local data dir; never falls back to the network.",
    },
}

# TTL cache so the scanner auto-refresh / charts / predictions don't hammer the
# free Yahoo feed (which rate-limits and returns empty candles → 404s).
_CACHE_TTL: dict[str, int] = {
    "get_quote": 60,
    "get_history": 900,
    "get_fundamentals": 1800,
    "get_option_chain": 1800,
}
_cache: dict[tuple, tuple[float, dict]] = {}


def _cache_key(method: str, provider: str, symbol: str, *, args: tuple = (), kwargs: dict | None = None) -> tuple:
    kw = tuple(sorted((kwargs or {}).items()))
    return (method, provider, symbol, args, kw)


def _cache_get(key: tuple, method: str):
    hit = _cache.get(key)
    if hit is None:
        return None
    ts, data = hit
    if time.time() - ts > _CACHE_TTL.get(method, 60):
        _cache.pop(key, None)
        return None
    return data


def _cache_set(key: tuple, method: str, data: dict) -> dict:
    if data is None:
        return data
    _cache[key] = (time.time(), data)
    if len(_cache) > 2048:
        now = time.time()
        for k, (ts, _d) in list(_cache.items()):
            if now - ts > max(_CACHE_TTL.values(), default=60):
                _cache.pop(k, None)
    return data


def resolve_provider(symbol: str, provider: str | None = None) -> tuple[MarketDataProvider, str]:
    """Pick a provider for a symbol.

    An explicit request always wins. Otherwise the exchange namespace picks a
    sensible default; otherwise the configured default provider is used.
    """
    if provider:
        prov = PROVIDERS.get(provider)
        if prov is None:
            raise ValueError(f"Unknown data provider '{provider}'. Available: {list(PROVIDERS)}")
        return prov, provider

    from app.services.data.providers import parse_symbol

    ex, _tick = parse_symbol(symbol)
    chosen = EXCHANGE_PROVIDER.get(ex) or settings.data_default_provider
    return PROVIDERS[chosen], chosen


class MarketDataService:
    """Facade that forwards calls to the resolved provider."""

    @staticmethod
    def _result_is_empty(method: str, data: dict | None) -> bool:
        """A provider "answered" but with no usable data (e.g. Yahoo rate-limit
        returns an empty candle set instead of raising). Empty answers are as
        useless as exceptions: do not cache them and do not treat them as real.
        Empty fundamentals stay legitimate (indices publish none), so only
        history/quote emptiness is treated as a miss."""
        if not data:
            return False
        if method == "get_history":
            return not data.get("candles")
        if method == "get_quote":
            return data.get("price") is None
        return False

    async def _with_fallback(self, method: str, symbol: str, provider: str | None, *args, **kwargs):
        prov, name = resolve_provider(symbol, provider)
        try:
            data = await getattr(prov, method)(*args, **kwargs)
        except Exception as exc:
            data = None
            if name != "yahoo":
                fb = PROVIDERS["yahoo"]
                logger.warning(
                    "provider '%s' failed for %s (falling back to yahoo): %s", name, symbol, exc
                )
                return await getattr(fb, method)(*args, **kwargs)
            raise
        if self._result_is_empty(method, data) and name != "yahoo":
            fb = PROVIDERS["yahoo"]
            logger.warning(
                "provider '%s' returned empty data for %s (falling back to yahoo)", name, symbol
            )
            return await getattr(fb, method)(*args, **kwargs)
        return data

    async def get_quote(self, symbol: str, provider: str | None = None) -> dict:
        return await self._cached("get_quote", symbol, provider, symbol)

    async def get_history(
        self, symbol: str, *, interval: str = "1d", period: str = "1y", provider: str | None = None
    ) -> dict:
        return await self._cached(
            "get_history", symbol, provider, symbol, kwargs={"interval": interval, "period": period}
        )

    async def get_fundamentals(self, symbol: str, provider: str | None = None) -> dict:
        return await self._cached("get_fundamentals", symbol, provider, symbol)

    async def get_option_chain(
        self, symbol: str, *, expiry: str | None = None, provider: str | None = None
    ) -> dict:
        return await self._cached(
            "get_option_chain", symbol, provider, symbol, kwargs={"expiry": expiry}
        )

    async def _cached(
        self,
        method: str,
        symbol: str,
        provider: str | None,
        *args: object,
        kwargs: dict | None = None,
    ) -> dict:
        prov, name = resolve_provider(symbol, provider)
        key = _cache_key(method, name, symbol, args=tuple(args), kwargs=kwargs)
        cached = _cache_get(key, method)
        if cached is not None:
            return cached
        data = await self._with_fallback(method, symbol, provider, *args, **(kwargs or {}))
        if self._result_is_empty(method, data):
            return data
        enriched = {
            **(data or {}),
            "provider": (data or {}).get("provider") or name,
        }
        return _cache_set(key, method, enriched)

    async def get_history_auto(
        self,
        symbol: str,
        *,
        interval: str = "1d",
        period: str = "1y",
        chain: list[str] | None = None,
    ) -> dict:
        """Smart history lookup: walk the per-market fallback chain.

        Returns the first non-empty, sanitized result. Degrades honestly to
        ``{"candles": [], "source": <last>, "error": <reason>}`` when every
        source fails, and attaches the ``source`` that actually served the data.
        """
        from app.services.data.fallback import chain_for, fetch_with_chain

        chain = chain or chain_for(symbol)
        result, source = await fetch_with_chain(
            PROVIDERS, "get_history", symbol, chain,
            interval=interval, period=period,
        )
        result = result or {}
        if result.get("candles"):
            result["source"] = source
            return result
        # Bare-ticker auto-resolve: a bare ticker with no data on its default
        # chain may still exist in the curated universe under an exchange prefix
        # (e.g. `RELIANCE` -> `NSE:RELIANCE`). Try those before giving up.
        resolved = await self._resolve_bare_history(symbol, interval=interval, period=period)
        if resolved is not None:
            return resolved
        return {
            "symbol": symbol,
            "interval": interval,
            "period": period,
            "candles": [],
            "source": source or None,
            "error": result.get("error"),
        }

    async def _resolve_bare_history(
        self, symbol: str, *, interval: str, period: str
    ) -> dict | None:
        """Try universe-canonical exchange forms of a bare ticker. Returns a
        sanitized history with the winning ``source`` or ``None`` if nothing
        resolves (kept out of the response so callers degrade honestly)."""
        from app.services.data.fallback import chain_for, fetch_with_chain
        from app.services.data.providers.base import parse_symbol

        ex, tick = parse_symbol(symbol)
        if ex or not tick:
            return None
        candidates = [f"NSE:{tick}", f"NYSE:{tick}", f"NASDAQ:{tick}"]
        for candidate in candidates:
            result, source = await fetch_with_chain(
                PROVIDERS, "get_history", candidate, chain_for(candidate),
                interval=interval, period=period,
            )
            result = result or {}
            if result.get("candles"):
                result["source"] = source
                result["symbol"] = candidate
                return result
        return None

    async def sources_status(self) -> dict:
        """Loader health + the per-market fallback chains (honest live probe)."""
        from app.services.data.fallback import chain_meta

        checks = await self.health()
        return {
            "providers": {
                name: {
                    **(PROVIDER_META.get(name) or {"display_name": prov.display_name}),
                    "reachable": checks.get(name, False),
                }
                for name, prov in PROVIDERS.items()
            },
            "fallback_chains": chain_meta(),
        }

    async def health(self, provider: str | None = None) -> dict[str, bool]:
        checks: dict[str, bool] = {}
        for name, prov in PROVIDERS.items():
            if provider and name != provider:
                continue
            try:
                checks[name] = await prov.health()
            except Exception:  # noqa: BLE001
                checks[name] = False
        return checks

    async def provider_status(self) -> dict:
        """Richer health readout: per-provider reachability + capability metadata.

        Reachability mirrors ``health()``; the rest is static metadata about
        which exchanges/data types each provider can serve (never fabricated
        health — ``reachable`` is a live probe). The default provider for each
        exchange namespace is highlighted so the UI can explain *why* a symbol
        is routed somewhere (e.g. NSE/BSE → tradingview).
        """
        checks = await self.health()
        default_for: dict[str, list[str]] = {}
        for ex, name in EXCHANGE_PROVIDER.items():
            default_for.setdefault(name, []).append(ex)
        ordered = dict(PROVIDERS)
        return {
            name: {
                **(PROVIDER_META.get(name) or {"display_name": prov.display_name}),
                "reachable": checks.get(name, False),
                "default_for": sorted(default_for.get(name, [])),
            }
            for name, prov in ordered.items()
        }


market_data = MarketDataService()
