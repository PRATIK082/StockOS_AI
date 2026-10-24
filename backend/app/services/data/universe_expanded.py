"""Enhanced universe service with complete stock database."""

from dataclasses import dataclass
from typing import List, Optional
from .full_universe import ALL_STOCKS, search_stocks as full_search_stocks

@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    name: str
    market: str  # "india" | "us"
    currency: str
    index: bool = False
    exchange: str = ""
    sector: str = ""

# Canonical platform index symbols (EXCHANGE:TICKER) — these are what the
# TradingView provider and the rest of the app expect for Indian options.
_INDICES = [
    SymbolInfo("NSE:NIFTY", "NIFTY 50 Index", "india", "INR", index=True, exchange="NSE"),
    SymbolInfo("NSE:BANKNIFTY", "NIFTY Bank Index", "india", "INR", index=True, exchange="NSE"),
    SymbolInfo("NSE:SENSEX", "BSE Sensex", "india", "INR", index=True, exchange="BSE"),
    SymbolInfo("NYSE:SPX", "S&P 500 Index", "us", "USD", index=True, exchange="NYSE"),
    SymbolInfo("NYSE:DJI", "Dow Jones Industrial Average", "us", "USD", index=True, exchange="NYSE"),
    SymbolInfo("NASDAQ:IXIC", "NASDAQ Composite", "us", "USD", index=True, exchange="NASDAQ"),
]

_INDEX_BY_SYMBOL = {i.symbol: i for i in _INDICES}

def get_all_symbols() -> List[SymbolInfo]:
    """Get all available symbols from the complete database."""
    symbols = []
    
    for symbol, data in ALL_STOCKS.items():
        # Skip duplicates (symbols with and without exchange prefix)
        if ":" in symbol:
            continue
            
        market = "india" if data.get("currency") == "INR" else "us"
        
        symbols.append(SymbolInfo(
            symbol=symbol,
            name=data.get("name", symbol),
            market=market,
            currency=data.get("currency", "USD"),
            index=False,
            exchange=data.get("exchange", ""),
            sector=data.get("sector", "")
        ))
    
    return list(_INDICES) + symbols

def search_symbols(query: str, market: Optional[str] = None, limit: int = 20) -> List[SymbolInfo]:
    """Search symbols by query string (stocks plus indices)."""
    q = (query or "").strip().lower()

    if not q:
        return get_all_symbols()[:limit]

    results = full_search_stocks(query, limit * 2)

    symbols = []
    # Indices must be searchable too ("nifty", "banknifty", "sensex", ...).
    for idx in _INDICES:
        if market and idx.market != market:
            continue
        if q in idx.symbol.lower() or q in idx.name.lower():
            symbols.append(idx)

    for item in results:
        symbol_market = "india" if item.get("currency") == "INR" else "us"
        
        # Filter by market if specified
        if market and symbol_market != market:
            continue
            
        symbols.append(SymbolInfo(
            symbol=item["symbol"],
            name=item["name"],
            market=symbol_market,
            currency=item.get("currency", "USD"),
            index=False,
            exchange=item.get("exchange", ""),
            sector=item.get("sector", "")
        ))
        
        if len(symbols) >= limit:
            break

    return symbols[:limit]

def get_market_symbols(market: str, limit: int = 50) -> List[SymbolInfo]:
    """Get top symbols for a specific market."""
    all_symbols = get_all_symbols()
    
    # Filter by market
    market_symbols = [s for s in all_symbols if s.market == market]
    
    # Prioritize indices and large caps
    indices = [s for s in market_symbols if s.index]
    stocks = [s for s in market_symbols if not s.index]
    
    return indices + stocks[:limit - len(indices)]

def get_indices() -> List[SymbolInfo]:
    """Get all available indices."""
    all_symbols = get_all_symbols()
    return [s for s in all_symbols if s.index]

def get_symbol_info(symbol: str) -> Optional[SymbolInfo]:
    """Get detailed info for a specific symbol."""
    # Try to find in ALL_STOCKS
    stock_data = None
    
    # Try exact match
    if symbol in ALL_STOCKS:
        stock_data = ALL_STOCKS[symbol]
    else:
        # Try with various prefixes/suffixes
        for test in [symbol.upper(), f"NSE:{symbol}", f"NYSE:{symbol}", f"NASDAQ:{symbol}", f"{symbol}.NS", f"{symbol}.BO"]:
            if test in ALL_STOCKS:
                stock_data = ALL_STOCKS[test]
                break
    
    if stock_data:
        market = "india" if stock_data.get("currency") == "INR" else "us"
        return SymbolInfo(
            symbol=symbol,
            name=stock_data.get("name", symbol),
            market=market,
            currency=stock_data.get("currency", "USD"),
            index=False,
            exchange=stock_data.get("exchange", ""),
            sector=stock_data.get("sector", "")
        )
    
    # Check if it's an index (canonical platform symbol first)
    key = symbol.upper()
    if key in _INDEX_BY_SYMBOL:
        return _INDEX_BY_SYMBOL[key]

    # Legacy Yahoo tickers (e.g. "^NSEI") map to the canonical symbol.
    legacy_index_map = {
        "^NSEI": "NSE:NIFTY",
        "^NSEBANK": "NSE:BANKNIFTY",
        "^BSESN": "NSE:SENSEX",
        "^GSPC": "NYSE:SPX",
        "^DJI": "NYSE:DJI",
        "^IXIC": "NASDAQ:IXIC",
    }
    if key in legacy_index_map:
        return _INDEX_BY_SYMBOL[legacy_index_map[key]]
    
    return None