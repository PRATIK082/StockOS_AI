"""Data tools for the vendored TradingAgents engine, backed by StockOS services.

Every tool keeps the EXACT name + signature of the vendored tool it replaces so
the LLM's function-calling schema stays identical (the agent prompts reference
these names). Internally each tool calls the StockOS ``market_data`` service,
the ``NewsService``, and the indicator module, so the engine analyses **real
local data** from the same providers the rest of StockOS uses (Yahoo, NSE/BSE
via TradingView, live options chains).

The engine graph is synchronous (LangGraph); StockOS data services are async.
Each tool therefore bridges via :func:`_run` (its own tiny event loop).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any

from langchain_core.tools import tool
import pandas as pd

from app.core.logging import get_logger
from app.services import indicators
from app.services.data.providers import parse_symbol
from app.services.data.service import market_data

logger = get_logger("tradingagents.data_port")

# ---------------------------------------------------------------------------
# Symbol mapping between StockOS EXCHANGE:TICKER and Yahoo-style tickers that
# the engine uses (RELIANCE.NS, ^NSEI, AAPL, ...).
# ---------------------------------------------------------------------------

_SUFFIX_EXCHANGE = {
    "NS": "NSE",
    "BO": "BSE",
}
_INDEX_MAP = {
    "^NSEI": "NSE:NIFTY",
    "^NSEBANK": "NSE:BANKNIFTY",
    "^BSESN": "BSE:SENSEX",
}


def to_stockos_symbol(symbol: str) -> str:
    """Convert an engine (Yahoo-style) ticker into StockOS EXCHANGE:TICKER."""
    s = (symbol or "").strip().upper()
    if s in _INDEX_MAP:
        return _INDEX_MAP[s]
    if s.endswith(".NS"):
        return f"NSE:{s[:-3]}"
    if s.endswith(".BO"):
        return f"BSE:{s[:-3]}"
    return s  # US/global tickers pass through to the Yahoo provider


def to_engine_symbol(symbol: str) -> str:
    """Convert a StockOS EXCHANGE:TICKER into a Yahoo-style ticker for the engine."""
    ex, ticker = parse_symbol(symbol)
    if ex == "NSE":
        if ticker in ("NIFTY", "NIFTY50"):
            return "^NSEI"
        if ticker in ("BANKNIFTY", "NIFTYBANK"):
            return "^NSEBANK"
        return f"{ticker.upper()}.NS"
    if ex == "BSE":
        if ticker in ("SENSEX", "BSESENSEX"):
            return "^BSESN"
        return f"{ticker.upper()}.BO"
    return ticker.upper()


def _run(coro) -> Any:
    """Bridge a StockOS async service call into the sync tool world."""
    return asyncio.run(coro)


def _period(months: int) -> str:
    if months <= 1:
        return "1mo"
    if months <= 3:
        return "3mo"
    if months <= 6:
        return "6mo"
    if months <= 12:
        return "1y"
    return "2y"


def _fetch_history(symbol: str, months: int = 12) -> pd.DataFrame:
    """Return a candles DataFrame for a symbol, or empty on failure."""
    try:
        data = _run(
            market_data.get_history(
                to_stockos_symbol(symbol), interval="1d", period=_period(months)
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("data_port history failed for %s: %s", symbol, exc)
        return pd.DataFrame()
    candles = (data or {}).get("candles") or []
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "ts" in df.columns:
        # Daily candles carry their exchange tz (e.g. +05:30, -04:00/-05:00
        # across DST) at wall-clock midnight. Parse just the calendar date so
        # tz-aware/naive mixes and DST offsets never break date filtering.
        df["date"] = pd.to_datetime(df["ts"].astype(str).str[:10], errors="coerce")
    return df


def _fmt_ohlcv(df: pd.DataFrame, rows: int = 40) -> str:
    if df.empty:
        return "No OHLCV data available for the requested period."
    cols = [c for c in ("date", "open", "high", "low", "close", "volume") if c in df.columns]
    return df[cols].tail(rows).to_string(index=False)


# ---------------------------------------------------------------------------
# Stock price data
# ---------------------------------------------------------------------------


@tool
def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve stock price data (OHLCV) for a given ticker symbol. Uses the StockOS market data service."""
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError:
        return "Invalid date range provided. Use yyyy-mm-dd format."
    months = max(1, round((end - start).days / 30))
    df = _fetch_history(symbol, months=min(months, 24))
    if df.empty:
        return f"No OHLCV data available for {symbol}."
    if "date" in df.columns:
        df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    return _fmt_ohlcv(df)


# ---------------------------------------------------------------------------
# Technical indicators
# ---------------------------------------------------------------------------


def _tail(s: pd.Series) -> float | None:
    v = s.dropna()
    return None if v.empty else round(float(v.iloc[-1]), 4)


def _fmt_indicator(title: str, values: dict) -> str:
    body = "\n".join(f"  {k}: {v}" for k, v in values.items() if v is not None)
    return f"{title}:\n{body}" if body else f"{title}: no data"


def _cross_text(macd_line: pd.Series, signal: pd.Series) -> str:
    diff = (macd_line - signal).dropna()
    if len(diff) < 2:
        return "no fresh cross"
    if diff.iloc[-2] <= 0 < diff.iloc[-1]:
        return "bullish macd cross (above signal)"
    if diff.iloc[-2] >= 0 > diff.iloc[-1]:
        return "bearish macd cross (below signal)"
    return "no fresh cross"


def _indicator_report(name: str, close: pd.Series) -> str:
    n = name.replace(" ", "").replace("_", "").lower()
    if n in ("sma", "ma", "movingaverage"):
        return _fmt_indicator(
            "Simple Moving Averages",
            {f"sma{p}": _tail(indicators.sma(close, p)) for p in (20, 50, 200)},
        )
    if n == "ema":
        return _fmt_indicators(
            "Exponential Moving Averages",
            {f"ema{p}": _tail(indicators.ema(close, p)) for p in (9, 21, 50)},
        )
    if n in ("rsi", "rsi14"):
        return _fmt_indicator("RSI (14)", {"rsi": _tail(indicators.rsi(close))})
    if n == "macd":
        macd_line, signal, hist = indicators.macd(close)
        return _fmt_indicator(
            "MACD",
            {
                "macd": _tail(macd_line),
                "signal": _tail(signal),
                "histogram": _tail(hist),
                "note": _cross_text(macd_line, signal),
            },
        )
    if n in ("bollinger", "bollingerbands"):
        mid = indicators.sma(close, 20)
        std = close.rolling(20).std()
        return _fmt_indicator(
            "Bollinger Bands (20, 2σ)",
            {
                "upper": _tail(mid + 2 * std),
                "mid": _tail(mid),
                "lower": _tail(mid - 2 * std),
                "last_close": _tail(close),
            },
        )
    return (
        f"Indicator '{name}' is not implemented here. Recognized: "
        "sma, ema, rsi, macd, bollinger. Use get_verified_market_snapshot for a "
        "compact summary instead."
    )


@tool
def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    """Retrieve a single technical indicator for a given ticker symbol. Uses StockOS indicators."""
    names = [i.strip().lower() for i in indicator.split(",") if i.strip()]
    df = _fetch_history(symbol, months=12)
    if df.empty or "close" not in df.columns:
        return f"No price data for {symbol} to compute {indicator}."
    close = df["close"]
    parts = [_indicator_report(name, close) for name in names]
    return "\n\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------


def _fmt_fundamentals(fund: dict) -> str:
    if not fund:
        return "No fundamental data returned by the feed for this instrument."
    lines = [f"Fundamentals for {fund.get('symbol', '?')}:"]
    for key, value in fund.items():
        if key in ("symbol", "provider", "longName"):
            continue
        if value is None or value == "":
            continue
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


@tool
def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """Retrieve comprehensive fundamental data for a given ticker symbol. Uses StockOS market data."""
    try:
        fund = _run(market_data.get_fundamentals(to_stockos_symbol(ticker)))
    except Exception as exc:  # noqa: BLE001
        return f"Fundamental data could not be fetched for {ticker}: {exc}"
    return _fmt_fundamentals(fund or {})


def _fin_statement(ticker: str, which: str) -> str:
    try:
        fund = _run(market_data.get_fundamentals(to_stockos_symbol(ticker)))
    except Exception:
        fund = {}
    return (
        f"Statement type '{which}' is not provided separately by the free feed. "
        f"Available fundamentals for {ticker}:\n\n{_fmt_fundamentals(fund or {})}"
    )


@tool
def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """Retrieve balance sheet data for a given ticker symbol."""
    return _fin_statement(ticker, "balance")


@tool
def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """Retrieve cash flow statement data for a given ticker symbol."""
    return _fin_statement(ticker, "cash flow")


@tool
def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """Retrieve income statement data for a given ticker symbol."""
    return _fin_statement(ticker, "income")


# ---------------------------------------------------------------------------
# News (real RSS feeds via StockOS NewsService)
# ---------------------------------------------------------------------------


async def _fetch_news_items(symbol: str | None, limit: int) -> list[dict]:
    from app.services.news.service import NewsService

    async with NewsService() as svc:
        symbols = None
        if symbol:
            _, ticker = parse_symbol(to_stockos_symbol(symbol))
            symbols = [ticker]
        items = await svc.fetch_news(symbols)
    out = []
    for it in items[:limit]:
        out.append(
            {
                "source": it.source,
                "title": it.title,
                "url": it.url,
                "sentiment": it.sentiment.value if hasattr(it, "sentiment") else "neutral",
                "impact": getattr(it, "impact_score", 0.0),
            }
        )
    return out


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve news data for a given ticker symbol. Uses StockOS news service (real RSS feeds)."""
    try:
        items = _run(_fetch_news_items(ticker.strip(), 12))
    except Exception as exc:  # noqa: BLE001
        return f"No news available for {ticker}: {exc}"
    if not items:
        return f"No recent news found for {ticker} in the available feeds."
    lines = [f"News for {ticker}:"]
    for it in items:
        lines.append(f"- [{it['source']}] ({it['sentiment']}; impact {it['impact']:.2f}) {it['title']} {it['url']}")
    return "\n".join(lines)


@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """Retrieve global market news from StockOS sources (MoneyControl/ET/Reuters/Bloomberg RSS)."""
    try:
        items = _run(_fetch_news_items(None, limit or 10))
    except Exception as exc:  # noqa: BLE001
        return f"No global news available: {exc}"
    if not items:
        return "No global market news returned by the RSS feeds right now."
    lines = ["Global market news:"]
    for it in items:
        lines.append(f"- [{it['source']}] ({it['sentiment']}) {it['title']} {it['url']}")
    return "\n".join(lines)


@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """Retrieve insider transaction information about a company. (Not on free feeds.)"""
    return (
        f"Insider transaction data for {ticker} is not available on the current "
        "free data feeds. Treat this gap explicitly — do not assume insider behavior."
    )


@tool
def get_macro_indicators(
    indicator: Annotated[str, "Macro indicator alias or raw FRED series id"],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Trailing window length in days; omit for a 1-year window"] = None,
) -> str:
    """Retrieve macroeconomic indicator time series (FRED). Optional vendor, off by default."""
    return (
        f"Macro indicator '{indicator}' is not configured: FRED is an optional "
        "vendor and StockOS free installs keep the engine on live market data."
    )


@tool
def get_prediction_markets(
    topic: Annotated[str, "Event topic/keyword, e.g. 'Fed rate cut'"],
    limit: Annotated[int | None, "Max markets to return; omit for a default of 6"] = None,
) -> str:
    """Retrieve live prediction-market odds. Vendor not enabled by default."""
    return (
        f"Prediction-market odds for '{topic}' are not enabled in this StockOS "
        "installation. Rely on the verified price/news data above instead."
    )


# ---------------------------------------------------------------------------
# Verified snapshot (market analyst grounding)
# ---------------------------------------------------------------------------


@tool
def get_verified_market_snapshot(
    symbol: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "the current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "number of recent trading rows to include for sanity-checking"] = 30,
) -> str:
    """Deterministic verification snapshot for exact market-data claims (price, RSI, MACD, MAs)."""
    df = _fetch_history(symbol, months=12)
    if df.empty or "close" not in df.columns:
        return "No price data available to build a snapshot."
    close = df["close"]
    macd_line, signal, _ = indicators.macd(close)
    snapshot = {
        "symbol": symbol,
        "as_of": str(df["date"].iloc[-1]) if "date" in df.columns else datetime.now().date().isoformat(),
        "last_close": _tail(close),
        "sma20": _tail(indicators.sma(close, 20)),
        "sma50": _tail(indicators.sma(close, 50)),
        "sma200": _tail(indicators.sma(close, 200)),
        "rsi14": _tail(indicators.rsi(close)),
        "macd": _tail(macd_line),
        "macd_signal": _tail(signal),
        "macd_note": _cross_text(macd_line, signal),
    }
    return "Verified Market Snapshot (StockOS market data):\n" + "\n".join(
        f"  {k}: {v}" for k, v in snapshot.items() if v is not None
    )


# ---------------------------------------------------------------------------
# Tool-node map for the StockOS graph (replaces the vendored ToolNode set)
# ---------------------------------------------------------------------------

TOOL_NODES: dict[str, list] = {
    "market": [get_stock_data, get_indicators, get_verified_market_snapshot],
    "social": [get_news],
    "news": [get_news, get_global_news, get_insider_transactions, get_macro_indicators, get_prediction_markets],
    "fundamentals": [get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement],
}