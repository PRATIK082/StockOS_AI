"""Execution protocol for market hours and trading sessions.

Implements the pre-market / market hours / post-market schedule from the
autonomous trading agent prompt (IST times).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import Enum
from typing import Literal, Optional


class MarketSession(Enum):
    """Current market session."""
    PRE_MARKET = "pre_market"
    SESSION_930_1100 = "9:30-11:00"
    SESSION_1100_1300 = "11:00-13:00"
    SESSION_1300_1500 = "13:00-15:00"
    SESSION_1500_1530 = "15:00-15:30"
    POST_MARKET = "post_market"
    CLOSED = "closed"


class MarketHours:
    """Market hours configuration (IST)."""

    # Market open/close times (IST - Indian Standard Time, UTC+5:30)
    MARKET_OPEN = time(9, 15)   # 9:15 AM IST
    MARKET_CLOSE = time(15, 30)  # 3:30 PM IST
    PRE_MARKET_START = time(8, 0)   # 8:00 AM IST
    POST_MARKET_END = time(18, 0)   # 6:00 PM IST

    # Session boundaries within market hours
    SESSION_930 = time(9, 30)   # 9:30 AM IST
    SESSION_1100 = time(11, 0)  # 11:00 AM IST
    SESSION_1300 = time(13, 0)  # 1:00 PM IST
    SESSION_1500 = time(15, 0)  # 3:00 PM IST

    # Emergency session boundaries
    MARKET_CRASH_THRESHOLD_PCT = 3.0  # NIFTY % drop for crash protocol


def get_current_session(dt: datetime | None = None) -> MarketSession:
    """Determine the current market session based on the given datetime (IST)."""
    if dt is None:
        dt = datetime.now()

    # Convert to IST for simplicity - assume input is already IST or we ignore TZ
    # For a real deployment, proper timezone conversion would be needed
    now_time = dt.time()

    # Post-market check (after 3:30 PM or after 6:00 PM)
    if now_time >= MarketHours.POST_MARKET_END or (now_time >= MarketHours.MARKET_CLOSE and now_time <= MarketHours.POST_MARKET_END):
        return MarketSession.POST_MARKET

    # Closed hours (before market open or specific holidays - simplified)
    if now_time < MarketHours.MARKET_OPEN and now_time < MarketHours.PRE_MARKET_START:
        return MarketSession.CLOSED

    # Pre-market (8:00-9:15 AM IST)
    if now_time < MarketHours.MARKET_OPEN:
        return MarketSession.PRE_MARKET

    # Market hours - determine sub-session
    if now_time < MarketHours.SESSION_930:
        return MarketSession.SESSION_930_1100  # Actually 9:15-9:30, but we group

    if now_time < MarketHours.SESSION_1100:
        return MarketSession.SESSION_930_1100

    if now_time < MarketHours.SESSION_1300:
        return MarketSession.SESSION_1100_1300

    if now_time < MarketHours.SESSION_1500:
        return MarketSession.SESSION_1300_1500

    # Last 30 minutes of trading (3:00-3:30 PM)
    return MarketSession.SESSION_1500_1530


def get_session_actions(session: MarketSession) -> list[str]:
    """Return the recommended actions for the current market session.

    Based on the execution protocol from the autonomous trading agent prompt.
    """
    actions_by_session = {
        MarketSession.PRE_MARKET: [
            "Scan global markets (US, Europe, Asia)",
            "Check SGX NIFTY / GIFT NIFTY for gap-up/down indication",
            "Review overnight news and corporate announcements",
            "Identify pre-market opportunities (stocks in F&O ban, earnings announcements)",
            "Set watchlist for the day (top 10 stocks by volume and volatility)",
        ],
        MarketSession.SESSION_930_1100: [
            "Observe market direction, avoid new entries (9:15-9:30 AM)",
            "Execute intraday strategies (momentum, breakout)",
            "Monitor open positions for early signals",
        ],
        MarketSession.SESSION_1100_1300: [
            "Monitor positions, adjust stop-losses",
            "Look for mean reversion opportunities",
            "Reduce exposure if portfolio is over-weighted",
        ],
        MarketSession.SESSION_1300_1500: [
            "Options selling strategies",
            "Position squaring and closure",
            "Reduce overall exposure ahead of close",
        ],
        MarketSession.SESSION_1500_1530: [
            "Close all intraday positions unless intentional carry-forward",
            "Final P&L assessment for the day",
            "Prepare watchlist and strategy plan for next day",
        ],
        MarketSession.POST_MARKET: [
            "Review all trades executed",
            "Calculate daily P&L and update performance metrics",
            "Analyze winning and losing trades for pattern recognition",
            "Adjust strategy parameters based on performance",
            "Prepare watchlist and strategy plan for next day",
        ],
        MarketSession.CLOSED: [
            "No trading activity",
            "Prepare for next market session",
            "Review overnight news",
        ],
    }

    return actions_by_session.get(session, [])


def is_trading_session(session: MarketSession) -> bool:
    """Check if the session is a trading session (not post-market or closed)."""
    return session in {
        MarketSession.PRE_MARKET,
        MarketSession.SESSION_930_1100,
        MarketSession.SESSION_1100_1300,
        MarketSession.SESSION_1300_1500,
        MarketSession.SESSION_1500_1530,
    }


def is_avoid_trading(session: MarketSession) -> bool:
    """Check if trading should be avoided in this session.

    The 9:15-9:30 AM period is explicitly avoided for new entries.
    """
    # 9:15-9:30 is part of the 9:30-11:00 group but we avoid new entries
    return session == MarketSession.SESSION_930_1100  # First 15 min avoided


# Export all public symbols
__all__ = [
    "MarketSession",
    "MarketHours",
    "get_current_session",
    "get_session_actions",
    "is_trading_session",
    "is_avoid_trading",
    "__all__",
]