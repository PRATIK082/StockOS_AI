"""Market data provider interface.

All data connectors (free and paid) implement this interface so consumers never
care which upstream is being used. Symbols use an exchange namespace, e.g.
`NSE:RELIANCE`, `NYSE:AAPL`. Bare symbols default to the configured provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# Canonical exchange prefixes understood by the platform.
KNOWN_EXCHANGES = {
    "NSE", "BSE", "NYSE", "NASDAQ", "AMEX", "BOM", "NSEFO", "BSEFO", "MCX", "NCDEX", "CBOE"
}


def parse_symbol(symbol: str) -> tuple[str, str]:
    """Split a symbol into (exchange, ticker). Bare ticker -> ("", ticker)."""
    symbol = (symbol or "").strip().upper()
    if ":" in symbol:
        ex, _, tick = symbol.partition(":")
        return ex.upper(), tick.strip()
    return "", symbol


def canonical_symbol(symbol: str) -> str:
    """Normalize to `EXCHANGE:TICKER`; bare tickers stay as-is."""
    ex, tick = parse_symbol(symbol)
    if not tick:
        raise ValueError(f"Empty ticker in symbol '{symbol}'")
    return f"{ex}:{tick}" if ex else tick


class OptionsUnavailableError(Exception):
    """Raised when a data provider cannot supply options chain data."""


class MarketDataProvider(ABC):
    """Abstract market data connector."""

    name: str = "base"
    display_name: str = "Base"

    @abstractmethod
    async def get_quote(self, symbol: str) -> dict:
        """Return a live/intraday quote for a symbol."""

    @abstractmethod
    async def get_history(self, symbol: str, *, interval: str = "1d", period: str = "1y") -> dict:
        """Return OHLCV history with 'dates' + 'candles' (list of dicts)."""

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> dict:
        """Return fundamental metrics for a symbol."""

    async def get_option_chain(self, symbol: str, *, expiry: str | None = None) -> dict:
        """Return a real options chain for a symbol.

        Shape: {symbol, expiry, spot_price, calls: [...], puts: [...]} where each
        option row has strike/bid/ask/last/volume/oi/iv. Providers that cannot
        supply options data should raise `OptionsUnavailableError` rather than
        fabricate a chain.
        """
        raise OptionsUnavailableError(f"Options data is not available from provider '{self.name}'")

    async def health(self) -> bool:
        return True
