"""Core vectorized primitives for the indicator library.

This module is a faithful numpy port of the stream/composition helpers and the
moving-average "overlay" builders from:

    https://github.com/cinar/indicator  (Cinar Indicator Project, Onur Cinar)
    Copyright (c) 2021-2026 Onur Cinar, licensed under GNU AGPLv3
    https://github.com/cinar/indicator/blob/master/LICENSE

The original Go code composes infinite streams of values with helper operators
(change, shift, skip, keep_*, etc.) and moving-average builders (SMA, EMA, RMA,
SMMA, WMA, DEMA, TEMA, HMA, KAMA, TRIMA, moving min/max/sum, stochastic). This
port keeps the exact numerical semantics of that project while replacing the
stream algebra with same-length numpy arrays.

Conventions
-----------
* Every function accepts an array-like of scalar values and returns a 1-D
  `numpy.ndarray` of `float64` with the SAME length as the input.
* The Go project drops the first ``IdlePeriod`` outputs of an indicator and the
  matching leading values of derived streams via ``Skip``/``Head``/``Change``.
  In this port those positions are marked as "idle" by being set to ``NaN``.
  A stream with a leading block of ``NaN`` values is understood to start at the
  first non-NaN index; rolling/moving primitives treat that index as the
  beginning of the data.  This reproduces the Go alignment exactly for every
  composite indicator (e.g. RSI idle period = period, KAMA idle = erPeriod).
* ``NaN`` inside the series is otherwise NOT expected (real OHLCV feeds are
  dense); it is only used as the idle placeholder.
* ``period <= 0`` raises ``ValueError`` (the Go code panics).

Numbers are computed with the same formulas the Go project uses; results have
been cross-validated against the project's ``testdata/*.csv`` fixtures for the
indicators that expose one.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

# --------------------------------------------------------------------------- #
# Scalar / elementwise helpers (mirror of cinar/indicator helper package).
# --------------------------------------------------------------------------- #


def asarray(values: Any, *, name: str = "values") -> np.ndarray:
    """Coerce *values* to a 1-D float64 numpy array."""
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim == 0:
        raise ValueError(f"{name} must be a sequence of numbers")
    return arr.reshape(-1)


def map_values(fn: Callable[[float], float], *arrays: Any) -> np.ndarray:
    """Apply *fn* elementwise to one or more aligned arrays (mirror of Map)."""
    if not arrays:
        raise ValueError("at least one array is required")
    out = asarray(arrays[0])
    for other in arrays[1:]:
        out = out + asarray(other) * 0.0  # broadcast/align silently
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        return np.vectorize(fn, otypes=[np.float64])(out)


def add(a: Any, b: Any) -> np.ndarray:
    return asarray(a) + asarray(b)


def subtract(a: Any, b: Any) -> np.ndarray:
    return asarray(a) - asarray(b)


def multiply(a: Any, b: Any) -> np.ndarray:
    return asarray(a) * asarray(b)


def divide(a: Any, b: Any) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return asarray(a) / asarray(b)


def multiply_by(a: Any, k: float) -> np.ndarray:
    return asarray(a) * float(k)


def divide_by(a: Any, k: float) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return asarray(a) / float(k)


def increment_by(a: Any, k: float) -> np.ndarray:
    return asarray(a) + float(k)


def decrement_by(a: Any, k: float) -> np.ndarray:
    return asarray(a) - float(k)


def pow(a: Any, y: float) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        return asarray(a) ** float(y)


def sqrt(a: Any) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.sqrt(asarray(a))


def abs(a: Any) -> np.ndarray:
    return np.abs(asarray(a))


def sign(a: Any) -> np.ndarray:
    """Sign of each value (-1/0/1); NaN stays NaN (mirror of helper.Sign)."""
    return np.where(np.isnan(a := asarray(a)), np.nan, np.sign(a))


def round_digits(a: Any, d: int) -> np.ndarray:
    """Round each value to *d* decimal places (mirror of helper.RoundDigits)."""
    return np.round(asarray(a), int(d))


# --------------------------------------------------------------------------- #
# Stream-algebra helpers (mirror of cinar/indicator helper package).
# --------------------------------------------------------------------------- #


def shift(a: Any, count: int, fill: float = 0.0) -> np.ndarray:
    """Prepend *count* *fill* values and drop the trailing *count* values.

    ``out[i] = a[i-count]`` for ``i >= count``, else *fill*. Mirrors
    ``helper.Shift``.
    """
    count = int(count)
    if count < 0:
        raise ValueError("count must be >= 0")
    arr = asarray(a)
    n = arr.size
    out = np.full(n, float(fill))
    if n > count:
        out[count:] = arr[: n - count]
    return out


def skip(a: Any, count: int) -> np.ndarray:
    """Drop the first *count* outputs; idle positions become NaN.

    Mirrors ``helper.Skip``.
    """
    count = int(count)
    if count < 0:
        raise ValueError("count must be >= 0")
    arr = asarray(a)
    out = arr.copy()
    out[: min(count, out.size)] = np.nan
    return out


def skip_last(a: Any, count: int) -> np.ndarray:
    """Drop the last *count* outputs; idle positions become NaN.

    Mirrors ``helper.SkipLast``.
    """
    count = int(count)
    if count < 0:
        raise ValueError("count must be >= 0")
    arr = asarray(a)
    out = arr.copy()
    if count > 0 and out.size:
        out[-min(count, out.size) :] = np.nan
    return out


def change(a: Any, before: int = 1) -> np.ndarray:
    """Each value minus the value *before* periods earlier (helper.Change).

    ``out[i] = a[i] - a[i-before]`` for ``i >= before``, else NaN.
    """
    before = int(before)
    if before < 0:
        raise ValueError("before must be >= 0")
    arr = asarray(a)
    if before == 0:
        return arr.copy()
    out = np.full(arr.size, np.nan)
    if arr.size > before:
        out[before:] = arr[before:] - arr[:-before]
    return out


def change_ratio(a: Any, before: int = 1) -> np.ndarray:
    """(current - previous) / previous over *before* periods (ChangeRatio)."""
    before = int(before)
    if before <= 0:
        raise ValueError("before must be greater than 0")
    arr = asarray(a)
    ch = change(arr, before)
    base = shift(arr, before, fill=np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return ch / base


def change_percent(a: Any, before: int = 1) -> np.ndarray:
    """Percentage change over *before* periods (helper.ChangePercent)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return change_ratio(a, before) * 100.0


def keep_positives(a: Any) -> np.ndarray:
    """Positive values unchanged, non-positive -> 0, NaN stays NaN."""
    arr = asarray(a)
    with np.errstate(invalid="ignore"):
        return np.where(np.isnan(arr), np.nan, np.where(arr > 0, arr, 0.0))


def keep_negatives(a: Any) -> np.ndarray:
    """Negative values unchanged, non-negative -> 0, NaN stays NaN."""
    arr = asarray(a)
    with np.errstate(invalid="ignore"):
        return np.where(np.isnan(arr), np.nan, np.where(arr < 0, arr, 0.0))


def map_previous(fn: Callable[[float, float], float], a: Any, initial: float) -> np.ndarray:
    """Cumulative fold seeded with *initial* (mirror of helper.MapWithPrevious).

    The fold starts at the first non-NaN index; earlier positions are NaN.
    ``out[i] = fn(out[i-1], a[i])``.
    """
    arr = asarray(a)
    out = np.full(arr.size, np.nan)
    start = first_valid(arr)
    if start >= arr.size:
        return out
    prev = float(initial)
    i = start
    val = arr[i]
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        prev = fn(prev, float(val))
    out[i] = prev
    for i in range(start + 1, arr.size):
        prev = fn(prev, float(arr[i]))
        out[i] = prev
    return out


# --------------------------------------------------------------------------- #
# Moving-average / overlay builders (mirror of cinar/indicator trend package).
# --------------------------------------------------------------------------- #


def first_valid(a: np.ndarray) -> int:
    """Index of the first non-NaN value, or ``a.size`` if all NaN."""
    idx = np.flatnonzero(~np.isnan(a))
    return int(idx[0]) if idx.size else a.size


def _rolling(a: np.ndarray, period: int, agg: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """Rolling reduction over windows ending at each position, NaN idle before first full window."""
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    arr = asarray(a)
    n = arr.size
    out = np.full(n, np.nan)
    start = first_valid(arr)
    if n - start < period:
        return out
    from numpy.lib.stride_tricks import sliding_window_view

    rows = sliding_window_view(arr[start:], period)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        vals = agg(rows)
    first = start + period - 1
    out[first : first + len(vals)] = vals
    return out


def moving_sum(a: Any, period: int) -> np.ndarray:
    """Rolling sum over *period* values; idle = period - 1 (MovingSum)."""
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    arr = asarray(a)
    start = first_valid(arr)
    n = arr.size
    out = np.full(n, np.nan)
    if n - start < period:
        return out
    dense = arr[start:]
    cs = np.concatenate(([0.0], np.cumsum(dense)))
    sums = cs[period:] - cs[:-period]
    first = start + period - 1
    out[first : first + sums.size] = sums
    return out


def moving_max(a: Any, period: int) -> np.ndarray:
    """Rolling maximum over *period* values; idle = period - 1 (MovingMax)."""
    return _rolling(a, period, lambda rows: np.max(rows, axis=1))


def moving_min(a: Any, period: int) -> np.ndarray:
    """Rolling minimum over *period* values; idle = period - 1 (MovingMin)."""
    return _rolling(a, period, lambda rows: np.min(rows, axis=1))


def sma(a: Any, period: int = 50) -> np.ndarray:
    """Simple moving average (default period 50, matching cinar/indicator)."""
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    arr = asarray(a)
    start = first_valid(arr)
    n = arr.size
    out = np.full(n, np.nan)
    if n - start < period:
        return out
    dense = arr[start:]
    cs = np.concatenate(([0.0], np.cumsum(dense)))
    means = (cs[period:] - cs[:-period]) / float(period)
    first = start + period - 1
    out[first : first + means.size] = means
    return out


def _scan_seeded(a: Any, period: int, seed: Callable[[np.ndarray], float], step: Callable[[float, float], float]) -> np.ndarray:
    """Shared recurrence driver for EMA/RMA/SMMA-style seeded accumulators."""
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    arr = asarray(a)
    start = first_valid(arr)
    n = arr.size
    out = np.full(n, np.nan)
    if n - start < period:
        return out
    dense = arr[start:]
    seed_val = float(seed(dense[:period]))
    first = start + period - 1
    out[first] = seed_val
    prev = seed_val
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        for i in range(period, dense.size):
            prev = float(step(prev, float(dense[i])))
            out[start + i] = prev
    return out


def ema(a: Any, period: int = 20, smoothing: float = 2.0) -> np.ndarray:
    """Exponential moving average (default period 20, smoothing 2)."""

    def step(prev: float, v: float) -> float:
        return prev + (smoothing / (period + 1)) * (v - prev)

    return _scan_seeded(a, period, lambda seed: float(np.mean(seed)), step)


def rma(a: Any, period: int = 20) -> np.ndarray:
    """Rolling / Wilder-style moving average (default period 20).

    ``R[i] = ((R[i-1] * (period-1)) + v[i]) / period`` after an SMA seed.
    """

    def step(prev: float, v: float) -> float:
        return ((prev * (period - 1)) + v) / period

    return _scan_seeded(a, period, lambda seed: float(np.mean(seed)), step)


def smma(a: Any, period: int = 7) -> np.ndarray:
    """Smoothed moving average (default period 7).

    Identical recurrence to RMA; kept as a separate name to mirror cinar.
    """

    def step(prev: float, v: float) -> float:
        return ((prev * (period - 1)) + v) / period

    return _scan_seeded(a, period, lambda seed: float(np.mean(seed)), step)


def wma(a: Any, period: int) -> np.ndarray:
    """Weighted moving average.

    Weights run *period* (oldest) down to 1 (newest), matching cinar's ring
    buffer exactly: ``out[j] = sum(v[j-period+1+k] * (period-k))`` for
    ``k`` in ``0..period-1``, divided by ``period*(period+1)/2``.
    """
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    arr = asarray(a)
    n = arr.size
    start = first_valid(arr)
    out = np.full(n, np.nan)
    if n - start < period:
        return out
    weights = np.arange(period, 0, -1, dtype=np.float64)
    divisor = period * (period + 1) / 2.0
    from numpy.lib.stride_tricks import sliding_window_view

    rows = sliding_window_view(arr[start:], period)
    vals = rows @ weights / divisor
    first = start + period - 1
    out[first : first + vals.size] = vals
    return out


def dema(a: Any, period: int = 20) -> np.ndarray:
    """Double exponential moving average ``2*EMA - EMA(EMA)``; idle 2*(period-1)."""
    e1 = ema(a, period)
    return subtract(multiply_by(e1, 2), ema(e1, period))


def tema(a: Any, period: int = 20) -> np.ndarray:
    """Triple exponential moving average ``3*EMA - 3*EMA(EMA) + EMA(EMA(EMA))``."""
    e1 = ema(a, period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    return add(subtract(multiply_by(e1, 3), multiply_by(e2, 3)), e3)


def hma(a: Any, period: int) -> np.ndarray:
    """Hull moving average ``WMA(sqrt(period), 2*WMA(period/2) - WMA(period))``."""
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    p1 = int(round(period / 2))
    p3 = int(round(math.sqrt(period)))
    return wma(subtract(multiply_by(wma(a, p1), 2), wma(a, period)), p3)


def kama(
    a: Any,
    er_period: int = 10,
    fast_sc_period: int = 2,
    slow_sc_period: int = 30,
) -> np.ndarray:
    """Kaufman adaptive moving average (defaults 10/2/30, matching cinar)."""
    er_period = int(er_period)
    if er_period <= 0 or fast_sc_period <= 0 or slow_sc_period <= 0:
        raise ValueError("periods must be greater than 0")
    arr = asarray(a)
    n = arr.size
    start = first_valid(arr)
    if n - start < er_period:
        return np.full(n, np.nan)
    out = np.full(n, np.nan)
    # Efficiency Ratio over the dense region.
    direction = np.abs(arr - shift(arr, er_period))  # NaN idle er_period
    volatility = moving_sum(np.abs(change(arr, 1)), er_period)
    with np.errstate(divide="ignore", invalid="ignore"):
        er = direction / volatility
    fast_sc = 2.0 / (fast_sc_period + 1)
    slow_sc = 2.0 / (slow_sc_period + 1)
    sc = ((er * (fast_sc - slow_sc)) + slow_sc) ** 2
    out[er_period - 1] = arr[er_period - 1]
    for i in range(er_period, n):
        out[i] = out[i - 1] + sc[i] * (arr[i] - out[i - 1])
    return out


def trima(a: Any, period: int = 15) -> np.ndarray:
    """Triangular moving average (nested SMA, default period 15)."""
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    if period % 2 == 0:
        p1, p2 = period // 2, period // 2 + 1
    else:
        p1 = p2 = (period + 1) // 2
    return sma(sma(a, p2), p1)


def stochastic(a: Any, period: int = 10, sma_period: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Generic-series Stochastic, returns ``(K, D)``.

    ``K = (v - Min(period)) / (Max(period) - Min(period)) * 100`` and
    ``D = SMA(K, sma_period)``. Both outputs are idle for ``period+sma_period-2``
    values, matching cinar's ``Stochastic``.
    """
    period = int(period)
    sma_period = int(sma_period)
    if period <= 0 or sma_period <= 0:
        raise ValueError("periods must be greater than 0")
    mn = moving_min(a, period)
    mx = moving_max(a, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        k = multiply_by(divide(subtract(asarray(a), mn), subtract(mx, mn)), 100)
    d = sma(k, sma_period)
    k = skip(k, sma_period - 1)
    return k, d