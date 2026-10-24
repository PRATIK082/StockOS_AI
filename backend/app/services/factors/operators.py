"""Vectorized factor operators (the alpha101 / GTJA operator vocabulary).

Every operator works on a pandas Series (per-symbol) or DataFrame
(cross-sectional panel); ``rank`` ranks cross-sectionally when given a
DataFrame and ranks the series' own history when given a Series (the
convention used by single-stock alpha101 ports). All windows are closed to the
past — a factor at bar ``t`` never sees bar ``t+1``. NaN-propagating windows
use ``min_periods=window`` so warm-up bars are NaN rather than fabricated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TSeries = pd.Series | pd.DataFrame


def _window(d: float | int) -> int:
    return max(1, int(round(float(d))))


def rank(x: TSeries) -> TSeries:
    """Cross-sectional (DataFrame) or series-history (Series) percentile rank."""
    return x.rank(pct=True)


def delay(x: TSeries, d: float | int) -> TSeries:
    return x.shift(_window(d))


def delta(x: TSeries, d: float | int) -> TSeries:
    return x.diff(_window(d))


def ts_sum(x: TSeries, d: float | int) -> TSeries:
    return x.rolling(_window(d), min_periods=_window(d)).sum()


def sum_(x: TSeries, d: float | int) -> TSeries:
    return ts_sum(x, d)


def ts_mean(x: TSeries, d: float | int) -> TSeries:
    return x.rolling(_window(d), min_periods=_window(d)).mean()


def ts_stddev(x: TSeries, d: float | int) -> TSeries:
    return x.rolling(_window(d), min_periods=_window(d)).std(ddof=0)


def ts_min(x: TSeries, d: float | int) -> TSeries:
    return x.rolling(_window(d), min_periods=_window(d)).min()


def ts_max(x: TSeries, d: float | int) -> TSeries:
    return x.rolling(_window(d), min_periods=_window(d)).max()


def ts_argmax(x: TSeries, d: float | int) -> TSeries:
    return x.rolling(_window(d), min_periods=_window(d)).apply(np.argmax, raw=True)


def ts_argmin(x: TSeries, d: float | int) -> TSeries:
    return x.rolling(_window(d), min_periods=_window(d)).apply(np.argmin, raw=True)


def ts_rank(x: TSeries, d: float | int) -> TSeries:
    """Ts_Rank: fraction of the last ``d`` values that are <= the current one."""
    return x.rolling(_window(d), min_periods=_window(d)).apply(
        lambda w: float(np.mean(w <= w[-1])), raw=True
    )


def ts_corr(x: TSeries, y: TSeries, d: float | int) -> TSeries:
    out = x.rolling(_window(d), min_periods=_window(d)).corr(y)
    return out.replace([np.inf, -np.inf], np.nan)


def ts_covariance(x: TSeries, y: TSeries, d: float | int) -> TSeries:
    out = x.rolling(_window(d), min_periods=_window(d)).cov(y)
    return out.replace([np.inf, -np.inf], np.nan)


def correlation(x: TSeries, y: TSeries, d: float | int) -> TSeries:
    return ts_corr(x, y, d)


def covariance(x: TSeries, y: TSeries, d: float | int) -> TSeries:
    return ts_covariance(x, y, d)


def scale(x: TSeries, a: float = 1.0) -> TSeries:
    """Scale so that sum(|x|) == a (a=1 default; 0 when degenerate)."""
    s = x.abs().sum()
    if not s or not np.isfinite(s) or s == 0:
        return x * 0.0
    return x * (a / s)


def sma(x: TSeries, d: float | int, m: float | int) -> TSeries:
    """Canonical alpha101 sma: EMA recursion with ratio m/d."""
    return x.ewm(alpha=float(m) / max(float(d), 1.0), adjust=False).mean()


def product(x: TSeries, d: float | int) -> TSeries:
    return x.rolling(_window(d), min_periods=_window(d)).apply(np.prod, raw=True)


def abs_(x: TSeries) -> TSeries:
    return x.abs()


def log(x: TSeries) -> TSeries:
    arr = np.log(np.where(np.asarray(x) > 0, np.asarray(x), np.nan))
    if isinstance(x, pd.Series):
        return pd.Series(arr, index=x.index)
    return arr


def sign(x: TSeries) -> TSeries:
    return np.sign(x)


def power(x: TSeries, e: float) -> TSeries:
    """SignedPower: sign(x) * |x|^e."""
    return np.sign(x) * np.abs(x) ** e


def minimum(a: TSeries, b: TSeries) -> TSeries:
    return np.minimum(a, b)


def maximum(a: TSeries, b: TSeries) -> TSeries:
    return np.maximum(a, b)


def decay_linear(x: TSeries, d: float | int) -> TSeries:
    """Linearly-decayed weighted mean over the last ``d`` values."""
    n = _window(d)
    w = np.arange(1, n + 1, dtype=float)
    w /= w.sum()
    return x.rolling(n, min_periods=n).apply(lambda a: float(np.dot(a, w)), raw=True)


def log_product(x: TSeries, d: float | int) -> TSeries:
    """LogProduct: log of the product of the last ``d`` values (sum of logs)."""
    return ts_sum(log(x), d)


def indneutralize(x: TSeries, g: pd.Series | None = None) -> TSeries:
    """Demean against group means when a group Series is supplied; identity
    otherwise (no industry classification data → documented no-op)."""
    if g is None:
        return x
    return x - x.groupby(g).transform("mean")


OPERATORS: dict[str, object] = {
    "rank": rank,
    "delay": delay,
    "delta": delta,
    "ts_sum": ts_sum,
    "ts_mean": ts_mean,
    "ts_stddev": ts_stddev,
    "ts_min": ts_min,
    "ts_max": ts_max,
    "ts_argmax": ts_argmax,
    "ts_argmin": ts_argmin,
    "ts_rank": ts_rank,
    "ts_corr": ts_corr,
    "ts_covariance": ts_covariance,
    "correlation": correlation,
    "covariance": covariance,
    "scale": scale,
    "sma": sma,
    "product": product,
    "abs": abs_,
    "log": log,
    "sign": sign,
    "power": power,
    "min": minimum,
    "max": maximum,
    "decay_linear": decay_linear,
    "log_product": log_product,
    "indneutralize": indneutralize,
}
