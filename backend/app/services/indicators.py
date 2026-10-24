"""Technical indicators (pandas based, no TA-Lib required).

Core indicator set used by the technical agent and scanners. Each function
accepts and returns pandas Series.
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    # Pure up moves (no losses) -> RSI 100; flat bars -> RSI 50.
    out = out.fillna(100.0)
    out[(avg_gain == 0) & (avg_loss == 0)] = 50.0
    return out


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, signal line, and histogram."""
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def sma_cross(series: pd.Series, fast: int = 20, slow: int = 50) -> pd.Series:
    """+1 when fast crosses above slow, -1 when crossing below, else 0."""
    fast_sma = sma(series, fast)
    slow_sma = sma(series, slow)
    diff = fast_sma - slow_sma
    prev = diff.shift(1)
    out = pd.Series(0, index=series.index)
    out[(prev <= 0) & (diff > 0)] = 1
    out[(prev >= 0) & (diff < 0)] = -1
    return out


def latest_signals(series: pd.Series) -> dict:
    """Return a compact JSON-able summary of the latest indicator values."""
    close = series
    ema9 = ema(close, 9)
    ema21 = ema(close, 21)
    ema50 = ema(close, 50)
    r = rsi(close)
    m_line, s_line, _ = macd(close)

    def tail(v: pd.Series) -> float | None:
        x = v.dropna()
        return None if x.empty else round(float(x.iloc[-1]), 4)

    return {
        "last_close": tail(close),
        "ema_9": tail(ema9),
        "ema_21": tail(ema21),
        "ema_50": tail(ema50),
        "rsi_14": tail(r),
        "macd": tail(m_line),
        "macd_signal": tail(s_line),
        "trend": "bullish" if tail(ema9) and tail(ema21) and tail(ema9) > tail(ema21) else "bearish",
    }
