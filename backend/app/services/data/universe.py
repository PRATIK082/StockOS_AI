"""Curation of well-known symbols for search/autocomplete and market views.

This is real, static symbol *metadata* (name, exchange, market, currency) used to
power search suggestions and market tabs — NOT fabricated price data. Prices are
always fetched live from data providers at render time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    name: str
    market: str  # "india" | "us"
    currency: str
    index: bool = False


UNIVERSE: list[SymbolInfo] = [
    # --- India (NSE/BSE) ---
    SymbolInfo("NSE:NIFTY", "NIFTY 50 Index", "india", "INR", index=True),
    SymbolInfo("NSE:BANKNIFTY", "NIFTY Bank Index", "india", "INR", index=True),
    SymbolInfo("NSE:SENSEX", "BSE Sensex", "india", "INR", index=True),
    SymbolInfo("NSE:RELIANCE", "Reliance Industries", "india", "INR"),
    SymbolInfo("NSE:TCS", "Tata Consultancy Services", "india", "INR"),
    SymbolInfo("NSE:HDFCBANK", "HDFC Bank", "india", "INR"),
    SymbolInfo("NSE:INFY", "Infosys", "india", "INR"),
    SymbolInfo("NSE:ICICIBANK", "ICICI Bank", "india", "INR"),
    SymbolInfo("NSE:SBIN", "State Bank of India", "india", "INR"),
    SymbolInfo("NSE:TATAMOTORS", "Tata Motors", "india", "INR"),
    SymbolInfo("NSE:LT", "Larsen & Toubro", "india", "INR"),
    SymbolInfo("NSE:ITC", "ITC Limited", "india", "INR"),
    SymbolInfo("NSE:AXISBANK", "Axis Bank", "india", "INR"),
    SymbolInfo("NSE:KOTAKBANK", "Kotak Mahindra Bank", "india", "INR"),
    SymbolInfo("NSE:BAJFINANCE", "Bajaj Finance", "india", "INR"),
    SymbolInfo("NSE:MARUTI", "Maruti Suzuki", "india", "INR"),
    SymbolInfo("NSE:HINDUNILVR", "Hindustan Unilever", "india", "INR"),
    SymbolInfo("NSE:ADANIENT", "Adani Enterprises", "india", "INR"),
    SymbolInfo("NSE:DLF", "DLF Limited", "india", "INR"),
    SymbolInfo("NSE:ZOMATO", "Zomato", "india", "INR"),
    SymbolInfo("NSE:TITAN", "Titan Company", "india", "INR"),
    SymbolInfo("NSE:BAJAJ-AUTO", "Bajaj Auto", "india", "INR"),
    SymbolInfo("NSE:WIPRO", "Wipro", "india", "INR"),
    SymbolInfo("NSE:LTIM", "LTIMindtree", "india", "INR"),
    SymbolInfo("BSE:TATASTEEL", "Tata Steel", "india", "INR"),
    SymbolInfo("BSE:SUNPHARMA", "Sun Pharmaceutical", "india", "INR"),
    SymbolInfo("BSE:DRREDDY", "Dr. Reddy's Laboratories", "india", "INR"),
    SymbolInfo("BSE:NTPC", "NTPC", "india", "INR"),
    SymbolInfo("BSE:POWERGRID", "Power Grid Corporation", "india", "INR"),
    # --- India mid / small caps ---
    SymbolInfo("NSE:TATAPOWER", "Tata Power", "india", "INR"),
    SymbolInfo("NSE:JSWSTEEL", "JSW Steel", "india", "INR"),
    SymbolInfo("NSE:COALINDIA", "Coal India", "india", "INR"),
    SymbolInfo("NSE:PIDILITIND", "Pidilite Industries", "india", "INR"),
    SymbolInfo("NSE:SRF", "SRF Limited", "india", "INR"),
    SymbolInfo("NSE:MUTHOOTFIN", "Muthoot Finance", "india", "INR"),
    SymbolInfo("NSE:HAVELLS", "Havells India", "india", "INR"),
    SymbolInfo("NSE:DABUR", "Dabur India", "india", "INR"),
    SymbolInfo("NSE:IRCTC", "IRCTC", "india", "INR"),
    SymbolInfo("NSE:INDIAMART", "IndiaMART InterMESH", "india", "INR"),
    SymbolInfo("NSE:POLICYBZR", "PB Fintech (PolicyBazaar)", "india", "INR"),
    SymbolInfo("NSE:KAJARIACER", "Kajaria Ceramics", "india", "INR"),
    SymbolInfo("NSE:CDSL", "CDSL", "india", "INR"),
    SymbolInfo("NSE:CESC", "CESC", "india", "INR"),
    SymbolInfo("NSE:ALKEM", "Alkem Laboratories", "india", "INR"),
    # --- India large caps across more sectors ---
    SymbolInfo("NSE:HCLTECH", "HCL Technologies", "india", "INR"),
    SymbolInfo("NSE:TECHM", "Tech Mahindra", "india", "INR"),
    SymbolInfo("NSE:ASIANPAINT", "Asian Paints", "india", "INR"),
    SymbolInfo("NSE:NESTLEIND", "Nestle India", "india", "INR"),
    SymbolInfo("NSE:BRITANNIA", "Britannia Industries", "india", "INR"),
    SymbolInfo("NSE:CIPLA", "Cipla", "india", "INR"),
    SymbolInfo("NSE:APOLLOHOSP", "Apollo Hospitals", "india", "INR"),
    SymbolInfo("NSE:DIVISLAB", "Divi's Laboratories", "india", "INR"),
    SymbolInfo("NSE:ULTRACEMCO", "UltraTech Cement", "india", "INR"),
    SymbolInfo("NSE:GRASIM", "Grasim Industries", "india", "INR"),
    SymbolInfo("NSE:ONGC", "Oil & Natural Gas Corporation", "india", "INR"),
    SymbolInfo("NSE:BPCL", "Bharat Petroleum", "india", "INR"),
    SymbolInfo("NSE:ADANIPORTS", "Adani Ports and SEZ", "india", "INR"),
    SymbolInfo("NSE:INDUSINDBK", "IndusInd Bank", "india", "INR"),
    SymbolInfo("NSE:HEROMOTOCO", "Hero MotoCorp", "india", "INR"),
    SymbolInfo("NSE:EICHERMOT", "Eicher Motors", "india", "INR"),
    SymbolInfo("NSE:ASHOKLEY", "Ashok Leyland", "india", "INR"),
    SymbolInfo("NSE:BHARTIARTL", "Bharti Airtel", "india", "INR"),
    SymbolInfo("NSE:VEDL", "Vedanta", "india", "INR"),
    # --- US ---
    SymbolInfo("NYSE:DJI", "Dow Jones Industrial Average", "us", "USD", index=True),
    SymbolInfo("NASDAQ:IXIC", "NASDAQ Composite", "us", "USD", index=True),
    SymbolInfo("NYSE:SPX", "S&P 500 Index", "us", "USD", index=True),
    SymbolInfo("NYSE:AAPL", "Apple Inc.", "us", "USD"),
    SymbolInfo("NASDAQ:MSFT", "Microsoft Corporation", "us", "USD"),
    SymbolInfo("NASDAQ:GOOGL", "Alphabet Inc.", "us", "USD"),
    SymbolInfo("NASDAQ:AMZN", "Amazon.com Inc.", "us", "USD"),
    SymbolInfo("NASDAQ:NVDA", "NVIDIA Corporation", "us", "USD"),
    SymbolInfo("NASDAQ:META", "Meta Platforms", "us", "USD"),
    SymbolInfo("NASDAQ:TSLA", "Tesla Inc.", "us", "USD"),
    SymbolInfo("NYSE:JPM", "JPMorgan Chase", "us", "USD"),
    SymbolInfo("NYSE:JNJ", "Johnson & Johnson", "us", "USD"),
    SymbolInfo("NYSE:WMT", "Walmart Inc.", "us", "USD"),
    SymbolInfo("NYSE:KO", "Coca-Cola Company", "us", "USD"),
    SymbolInfo("NYSE:PEP", "PepsiCo Inc.", "us", "USD"),
    SymbolInfo("NYSE:XOM", "Exxon Mobil", "us", "USD"),
    SymbolInfo("NYSE:V", "Visa Inc.", "us", "USD"),
    SymbolInfo("NYSE:BA", "Boeing", "us", "USD"),
    SymbolInfo("NYSE:DIS", "Walt Disney Company", "us", "USD"),
    # --- US mid / small caps ---
    SymbolInfo("NASDAQ:SNOW", "Snowflake", "us", "USD"),
    SymbolInfo("NASDAQ:CRWD", "CrowdStrike", "us", "USD"),
    SymbolInfo("NYSE:SPOT", "Spotify Technology", "us", "USD"),
    SymbolInfo("NYSE:PLTR", "Palantir Technologies", "us", "USD"),
    SymbolInfo("NASDAQ:DDOG", "Datadog", "us", "USD"),
    SymbolInfo("NASDAQ:ZM", "Zoom Video", "us", "USD"),
    SymbolInfo("NASDAQ:UBER", "Uber Technologies", "us", "USD"),
]

_TICKER_ALIAS = {s.symbol.split(":", 1)[1]: s for s in UNIVERSE}


def search_symbols(query: str, market: str | None = None, limit: int = 10) -> list[dict]:
    q = (query or "").strip().lower()
    matches: list[SymbolInfo] = []
    for s in UNIVERSE:
        if market and s.market != market:
            continue
        if not q:
            matches.append(s)
            continue
        if q in s.symbol.lower() or q in s.name.lower():
            matches.append(s)
            continue

    # Rank prefix matches on ticker first, then name, then secondary folder.
    def rank(s: SymbolInfo) -> int:
        sym_l = s.symbol.lower()
        name_l = s.name.lower()
        if q and sym_l.startswith(q):
            return 0
        if q and name_l.startswith(q):
            return 1
        return 2

    matches.sort(key=lambda s: (rank(s), s.symbol))
    return [to_dict(s) for s in matches[:limit]]


def to_dict(s: SymbolInfo) -> dict:
    return {
        "symbol": s.symbol,
        "name": s.name,
        "market": s.market,
        "currency": s.currency,
        "index": s.index,
    }


def indices(market: str) -> list[dict]:
    return [to_dict(s) for s in UNIVERSE if s.index and s.market == market]


def by_market(market: str) -> list[dict]:
    return [to_dict(s) for s in UNIVERSE if s.market == market]