"""OHLCV validation, sanitization and resampling helpers.

Central quality gate for every market-data path (providers, fallback chains,
backtests, factor pipelines). Guarantees:
- only finite numbers survive (no NaN / inf),
- prices are strictly positive,
- OHLC invariants hold: low <= open <= high, low <= close <= high,
- interval values are validated up-front (fail fast, never silent daily),
- a uniform annualization factor per interval (for annualized metrics).
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

# Canonical intervals understood across the platform.
SUPPORTED_INTERVALS = {
    "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M",
}
# Aliases normalised to canonical intervals.
_INTERVAL_ALIASES = {
    "1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m",
    "60min": "1h", "1H": "1h", "4H": "4h", "1D": "1d", "1W": "1w", "1MO": "1M",
    "1wk": "1w", "1mo": "1M",
}

# Trading periods per year used to annualize volatility/returns.
_ANNUALIZATION = {
    "1m": 252 * 6.5 * 60,   # ~1,022,400 minutes... capped below
    "5m": 252 * 78,
    "15m": 252 * 26,
    "30m": 252 * 13,
    "1h": 252 * 6.5,
    "4h": 252 * 6.5 / 4,
    "1d": 252,
    "1w": 52,
    "1M": 12,
}
# Realistic cap for 1m (US session is 6.5h -> 390 bars/day)
_ANNUALIZATION["1m"] = 252 * 390


def normalize_interval(interval: str) -> str:
    """Map a user-supplied interval to a canonical value or raise."""
    if interval is None:
        return "1d"
    key = str(interval).strip().lower()
    if key in _INTERVAL_ALIASES:
        return _INTERVAL_ALIASES[key]
    if key in SUPPORTED_INTERVALS:
        return key
    # accept e.g. "4h" lowercase already handled; anything unknown fails fast.
    raise ValueError(
        f"Unsupported interval '{interval}'. Supported: {sorted(SUPPORTED_INTERVALS)}"
    )


def annualization_factor(interval: str) -> float:
    """Trading periods per year for a canonical interval (used by metrics)."""
    return float(_ANNUALIZATION.get(normalize_interval(interval), 252))


def _finite(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _valid_candle(row: Any, open_k: str, high_k: str, low_k: str, close_k: str) -> bool:
    """Return True only when a candle satisfies every OHLC invariant."""
    o, h, l, c = (row.get(open_k), row.get(high_k), row.get(low_k), row.get(close_k))
    if not all(_finite(v) for v in (o, h, l, c)):
        return False
    o, h, l, c = float(o), float(h), float(l), float(c)
    if o <= 0 or h <= 0 or l <= 0 or c <= 0:
        return False
    if h < l:
        return False
    if not (l <= o <= h and l <= c <= h):
        return False
    return True


def sanitize_history(history: dict[str, Any]) -> dict[str, Any]:
    """Drop dirty bars from a history dict in place of a new clean copy.

    Keeps the response shape used by every provider
    (``{symbol, interval, period, candles: [{ts, open, high, low, close, volume}]}``)
    and guarantees the returned candles are valid + finite.
    """
    if not history:
        return history or {}
    candles = history.get("candles") or []
    clean: list[dict[str, Any]] = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        if not _valid_candle(c, "open", "high", "low", "close"):
            continue
        vol = c.get("volume")
        clean.append(
            {
                "ts": c.get("ts"),
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": int(vol) if _finite(vol) else 0,
            }
        )
    return {**history, "candles": clean}


def to_dataframe(history: dict[str, Any]) -> pd.DataFrame:
    """Convert a provider history dict into an indexed OHLCV DataFrame.

    Returns an empty DataFrame when there is no data. The index is a sorted
    pandas DatetimeIndex (naive timestamps parsed defensively).
    """
    candles = (history or {}).get("candles") or []
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        [
            {
                "ts": c["ts"],
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c.get("volume") or 0),
            }
            for c in candles
        ]
    )
    try:
        idx = pd.to_datetime(df["ts"], errors="coerce")
    except Exception:  # noqa: BLE001
        idx = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df["ts"] = idx
    df = df.dropna(subset=["ts"]).set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def dataframe_to_history(df: pd.DataFrame, *, symbol: str, interval: str) -> dict[str, Any]:
    """Convert an indexed OHLCV DataFrame back into a provider-style history dict."""
    candles: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        candles.append(
            {
                "ts": ts.isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row.get("volume") or 0),
            }
        )
    return {"symbol": symbol, "interval": interval, "candles": candles}


def merge_history(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Merge two history dicts, preferring the primary symbol/interval metadata.

    Used by fallback chains when a secondary source covers dates a primary
    source does not (bars are unioned on timestamp, deduplicated, re-sorted).
    """
    df1 = to_dataframe(primary)
    df2 = to_dataframe(fallback)
    if df1.empty:
        return fallback
    if df2.empty:
        return primary
    combined = pd.concat([df1, df2[~df2.index.isin(df1.index)]])
    combined = combined[~combined.index.duplicated(keep="first")].sort_index()
    return dataframe_to_history(combined, symbol=primary.get("symbol"), interval=primary.get("interval"))


def min_bars(interval: str) -> int:
    """Minimum sensible candle count before analysis may proceed."""
    return 30 if normalize_interval(interval) in {"1d", "1w", "1M"} else 60
