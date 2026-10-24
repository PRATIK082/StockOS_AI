"""Per-market fallback chains for market-data lookups.

Vibe-Trading-style "smart routing": one call tries a chain of providers in
order of IP-ban risk (free, never-banned public sources first; throttled
sources last) and returns the first non-empty sanitized result. A ``local:``
symbol never falls back to the network; an explicit provider never goes through
the chain.
"""

from __future__ import annotations

from typing import Any

from app.services.data.ohlcv import sanitize_history, to_dataframe

# Exchange namespace -> ordered provider chain for `source=auto`.
# Ordered by reliability + IP-ban risk; yahoo stays a workhorse, stooq/crypto
# are keyless fallbacks, `local` is the last resort.
FALLBACK_CHAINS: dict[str, list[str]] = {
    "NSE": ["tradingview", "yahoo", "stooq", "local"],
    "BSE": ["tradingview", "yahoo", "stooq", "local"],
    "BOM": ["tradingview", "yahoo", "stooq", "local"],
    "NSEFO": ["tradingview", "yahoo", "stooq", "local"],
    "BSEFO": ["tradingview", "yahoo", "stooq", "local"],
    "NYSE": ["yahoo", "stooq", "local"],
    "NASDAQ": ["yahoo", "stooq", "local"],
    "AMEX": ["yahoo", "stooq", "local"],
    "BINANCE": ["crypto", "local"],
    "CRYPTO": ["crypto", "local"],
    "LOCAL": ["local"],  # explicit local: never touches the network
}

DEFAULT_CHAIN = ["yahoo", "stooq", "local"]

# Providers whose "no data" answer is a real answer and must not be skipped.
# (an empty result from stooq for a covered symbol is a hard miss).


def chain_for(symbol: str) -> list[str]:
    """Return the ordered provider chain for a symbol's exchange namespace."""
    from app.services.data.providers.base import parse_symbol

    ex, _tick = parse_symbol(symbol)
    return FALLBACK_CHAINS.get(ex.upper(), DEFAULT_CHAIN)


def chain_meta() -> dict[str, dict]:
    """Human-readable chain readout for the health/status endpoint."""
    return {
        ex: {"order": providers, "symbols": [f"{ex}:*"]}
        for ex, providers in FALLBACK_CHAINS.items()
    }


async def fetch_with_chain(
    providers: dict[str, Any],
    method: str,
    symbol: str,
    chain: list[str],
    *args,
    **kwargs,
) -> tuple[dict, str]:
    """Try each provider in `chain` and return the first non-empty sanitized result.

    Returns ``({}, last_provider)`` when every source fails, so callers can
    degrade honestly instead of guessing.
    """
    last_error: str | None = None
    for name in chain:
        prov = providers.get(name)
        if prov is None:
            continue
        try:
            result = await getattr(prov, method)(symbol, *args, **kwargs)
            if method == "get_history":
                result = sanitize_history(result or {})
                df = to_dataframe(result)
                if df.empty:
                    last_error = f"{name} returned no candles"
                    continue
                return result, name
            if result:
                return result, name
            last_error = f"{name} returned an empty result"
        except Exception as exc:  # noqa: BLE001
            last_error = f"{name}: {exc}"
            continue
    return {}, last_error or "no providers in chain"
