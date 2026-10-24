"""Volatility indicators ported from the Go library github.com/cinar/indicator.

This module is a numpy port of the volatility package of:

    https://github.com/cinar/indicator  (Cinar Indicator Project, Onur Cinar)
    Copyright (c) 2021-2026 Onur Cinar, licensed under GNU AGPLv3
    https://github.com/cinar/indicator/blob/master/LICENSE

Every function faithfully reproduces the exact arithmetic, idle-period and
alignment semantics of the matching Go file (which is the spec). Cinar's
stream model is mapped to same-length numpy arrays: "idle" leading positions
are ``np.nan`` and the rolling primitives from ``_core`` align on the first
non-NaN index, which reproduces Go's Skip/Head/Change behaviour exactly.

Conventions
-----------
* Every function takes array-like float inputs in the same order as the Go
  ``Compute`` method and returns a ``numpy.ndarray`` (float64) of the same
  length, or a tuple of arrays for multi-output indicators.
* Inputs are any array-like (list / numpy / pandas Series); outputs are
  always numpy float64 1-D arrays.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ._core import (
    add,
    asarray,
    change_ratio,
    divide,
    divide_by,
    first_valid,
    hma,
    increment_by,
    moving_max,
    moving_min,
    moving_sum,
    multiply,
    multiply_by,
    pow,
    shift,
    skip,
    sma,
    sqrt,
    subtract,
)

_DEFAULT_ACCELERATION_BANDS_PERIOD = 20
_DEFAULT_ANNUALIZED_HISTORICAL_VOLATILITY_PERIOD = 21
_DEFAULT_TRADING_DAYS_PER_YEAR = 252
_DEFAULT_ATR_PERIOD = 14
_DEFAULT_BOLLINGER_BANDS_PERIOD = 20
_DEFAULT_CHANDELIER_EXIT_PERIOD = 22
_DEFAULT_CHANDELIER_EXIT_MULTIPLIER = 3
_DEFAULT_CHOP_PERIOD = 14
_DEFAULT_DONCHIAN_CHANNEL_PERIOD = 20
_DEFAULT_HISTORICAL_VOLATILITY_PERIOD = 21
_DEFAULT_KELTNER_CHANNEL_PERIOD = 20
_DEFAULT_MOVING_STD_PERIOD = 1
_DEFAULT_PO_PERIOD = 14
_DEFAULT_SUPER_TREND_PERIOD = 14
_DEFAULT_SUPER_TREND_MULTIPLIER = 2.5
_DEFAULT_ULCER_INDEX_PERIOD = 14
_DEFAULT_Z_SCORE_PERIOD = 20


def tr(high: object, low: object, closing: object) -> np.ndarray:
    """True Range ``max(H-L, H-prevC, prevC-L)`` (signed, no abs), idle 1.

    Returns: numpy float64 array of same length as inputs.
    """
    h1 = skip(high, 1)
    l1 = skip(low, 1)
    pc = shift(closing, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.maximum(np.maximum(h1 - l1, h1 - pc), pc - l1)


def _atr(
    high: object,
    low: object,
    closing: object,
    period: int,
    ma: Callable[[object, int], np.ndarray],
) -> np.ndarray:
    """ATR = moving average of the true range; idle = ma idle + 1."""
    true_range = tr(high, low, closing)
    return ma(true_range, period)


def atr(
    high: object,
    low: object,
    closing: object,
    period: int = _DEFAULT_ATR_PERIOD,
    ma: Callable[[object, int], np.ndarray] | None = None,
) -> np.ndarray:
    """Average True Range, SMA smoothing by default (idle = period).

    ``ma`` overrides the smoothing moving average (callable taking the
    series and the period, e.g. ``hma`` or ``rma``); None means SMA.
    """
    return _atr(high, low, closing, period, ma if ma is not None else sma)


def _moving_std_window(a: object, period: int) -> np.ndarray:
    """Population rolling std over [i-period+1, i]; idle = period - 1."""
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    arr = asarray(a)
    n = arr.size
    start = first_valid(arr)
    out = np.full(n, np.nan)
    if n - start < period:
        return out
    if period == 1:
        out[start:] = 0.0
        return out
    dense = arr[start:]
    cs = np.concatenate(([0.0], np.cumsum(dense)))
    sums = cs[period:] - cs[:-period]
    means = sums / float(period)
    rows = np.lib.stride_tricks.sliding_window_view(dense, period)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        var = np.sum((rows - means[:, None]) ** 2, axis=1) / float(period)
        stds = np.sqrt(var)
    first = start + period - 1
    out[first : first + stds.size] = stds
    return out


def moving_std(
    c: object, period: int = _DEFAULT_MOVING_STD_PERIOD
) -> np.ndarray:
    """Moving standard deviation over a period window (population divisor).

    ``std = sqrt(1/period * sum((value - mean)^2))``; idle = period - 1.
    """
    return _moving_std_window(c, period)


def _ema(a: object, period: int, smoothing: float = 2.0) -> np.ndarray:
    """Exponential moving average seeded with SMA(period); idle = period-1."""
    period = int(period)
    if period <= 0:
        raise ValueError("period must be greater than 0")
    arr = asarray(a)
    n = arr.size
    start = first_valid(arr)
    out = np.full(n, np.nan)
    if n - start < period:
        return out
    dense = arr[start:]
    seed = float(np.mean(dense[:period]))
    first = start + period - 1
    out[first] = seed
    prev = seed
    mult = smoothing / (period + 1)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        for i in range(period, dense.size):
            prev = prev + mult * (float(dense[i]) - prev)
            out[start + i] = prev
    return out


def _mls_slope(x: object, y: object, period: int) -> np.ndarray:
    """Least-squares slope m = (p*sumXY - sumX*sumY)/(p*sumX2 - sumX^2)."""
    p = float(period)
    sum_xy = moving_sum(multiply(x, y), period)
    sum_x = moving_sum(x, period)
    sum_y = moving_sum(y, period)
    sum_x2 = moving_sum(pow(x, 2), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        return divide(
            subtract(multiply_by(sum_xy, p), multiply(sum_x, sum_y)),
            subtract(multiply_by(sum_x2, p), multiply(sum_x, sum_x)),
        )


def historical_volatility(
    closing: object, period: int = _DEFAULT_HISTORICAL_VOLATILITY_PERIOD
) -> np.ndarray:
    """Std of 1-period change ratios ``(P_t/P_(t-1)) - 1``; idle = period."""
    returns = change_ratio(closing, 1)
    return _moving_std_window(returns, period)


def annualized_historical_volatility(
    closing: object,
    period: int = _DEFAULT_ANNUALIZED_HISTORICAL_VOLATILITY_PERIOD,
    trading_days_per_year: int = _DEFAULT_TRADING_DAYS_PER_YEAR,
) -> np.ndarray:
    """Historical volatility scaled by ``sqrt(trading_days_per_year)``."""
    hv = historical_volatility(closing, period)
    return multiply_by(hv, np.sqrt(float(trading_days_per_year)))


def bollinger_bands(
    closing: object,
    period: int = _DEFAULT_BOLLINGER_BANDS_PERIOD,
    mult: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands (upper, middle, lower); middle = SMA(period).

    ``upper = SMA + mult*std``, ``lower = SMA - mult*std``; idle = period-1.
    """
    mid = sma(closing, period)
    std = _moving_std_window(closing, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        upper = add(mid, multiply_by(std, mult))
        lower = subtract(mid, multiply_by(std, mult))
    return upper, mid, lower


def bollinger_band_width(
    closing: object,
    period: int = _DEFAULT_BOLLINGER_BANDS_PERIOD,
    mult: float = 2.0,
) -> np.ndarray:
    """Bollinger Band Width ``(Upper - Lower) / Middle``; idle = period-1."""
    upper, middle, lower = bollinger_bands(closing, period, mult)
    with np.errstate(divide="ignore", invalid="ignore"):
        return divide(subtract(upper, lower), middle)


def percent_b(
    closing: object, period: int = _DEFAULT_BOLLINGER_BANDS_PERIOD
) -> np.ndarray:
    """%B ``(Close - Lower) / (Upper - Lower)``; idle = period-1."""
    upper, _, lower = bollinger_bands(closing, period)
    cs = skip(closing, period - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return divide(subtract(cs, lower), subtract(upper, lower))


def z_score(
    closing: object, period: int = _DEFAULT_Z_SCORE_PERIOD
) -> np.ndarray:
    """Z-Score ``(Price - SMA) / StdDev``; idle = period-1."""
    sma_ = sma(closing, period)
    std = _moving_std_window(closing, period)
    cs = skip(closing, period - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return divide(subtract(cs, sma_), std)


def donchian_channel(
    closing: object, period: int = _DEFAULT_DONCHIAN_CHANNEL_PERIOD
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Donchian Channel (upper, middle, lower) over period highs/lows.

    ``upper = MovingMax(period)``, ``lower = MovingMin(period)``,
    ``middle = (upper + lower) / 2``; idle = period-1.
    """
    upper = moving_max(closing, period)
    lower = moving_min(closing, period)
    middle = divide_by(add(upper, lower), 2)
    return upper, middle, lower


def acceleration_bands(
    high: object,
    low: object,
    closing: object,
    period: int = _DEFAULT_ACCELERATION_BANDS_PERIOD,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Acceleration Bands (upper, middle, lower).

    ``upper = SMA(High * (1 + 4*(H-L)/(H+L)))``,
    ``middle = SMA(Closing)``,
    ``lower = SMA(Low * (1 - 4*(H-L)/(H+L)))``; idle = period-1.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ks = divide(subtract(high, low), add(high, low))
        upper = sma(multiply(high, increment_by(multiply_by(ks, 4), 1)), period)
        middle = sma(closing, period)
        lower = sma(multiply(low, increment_by(multiply_by(ks, -4), 1)), period)
    return upper, middle, lower


def chandelier_exit(
    high: object,
    low: object,
    closing: object,
    period: int = _DEFAULT_CHANDELIER_EXIT_PERIOD,
    multiplier: float = _DEFAULT_CHANDELIER_EXIT_MULTIPLIER,
) -> tuple[np.ndarray, np.ndarray]:
    """Chandelier Exit (long stop, short stop); idle = period.

    ``long = MovingMax(High, p) - ATR(p)*mult``,
    ``short = MovingMin(Low, p) + ATR(p)*mult``.
    """
    a = _atr(high, low, closing, period, sma)
    max_high = skip(moving_max(high, period), 1)
    min_low = skip(moving_min(low, period), 1)
    a3 = multiply_by(a, multiplier)
    long_stop = subtract(max_high, a3)
    short_stop = add(min_low, a3)
    return long_stop, short_stop


def chop(
    high: object,
    low: object,
    closing: object,
    period: int = _DEFAULT_CHOP_PERIOD,
) -> np.ndarray:
    """Choppiness Index ``100*log10(sum(TR, n)/(max(H)-min(L)))/log10(n)``.

    Idle = period; returns 0 where the period range is zero.
    """
    p = int(period)
    if p <= 0:
        raise ValueError("period must be greater than 0")
    sum_tr = moving_sum(tr(high, low, closing), p)
    max_high = moving_max(skip(high, 1), p)
    min_low = moving_min(skip(low, 1), p)
    log10n = np.log10(float(p))
    diff = subtract(max_high, min_low)
    with np.errstate(divide="ignore", invalid="ignore"):
        val = multiply_by(np.log10(divide(sum_tr, diff)), 100.0) / float(log10n)
    return np.where(diff == 0, 0.0, val)


def keltner_channel(
    high: object,
    low: object,
    closing: object,
    period: int = _DEFAULT_KELTNER_CHANNEL_PERIOD,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keltner Channel (upper, middle, lower).

    ``middle = EMA(period)``, bands = middle +/- 2*ATR(period); idle = period.
    """
    a = _atr(high, low, closing, period, sma)
    mid = skip(_ema(closing, period), 1)
    a2 = multiply_by(a, 2)
    upper = add(mid, a2)
    lower = subtract(mid, a2)
    return upper, mid, lower


def po(
    high: object,
    low: object,
    closing: object,
    period: int = _DEFAULT_PO_PERIOD,
) -> np.ndarray:
    """Projection Oscillator ``100*(Close - PL)/(PH - PL)``; idle = 2*(p-1).

    ``PL = Min(p, high + MLS(p, x, high))``,
    ``PH = Max(p, low + MLS(p, x, low))`` with ``x = 1, 2, 3, ...``.
    """
    p = int(period)
    n = int(asarray(closing).size)
    x = np.arange(1, n + 1, dtype=np.float64)
    pl_m = _mls_slope(x, high, p)
    ph_m = _mls_slope(x, low, p)
    pl = moving_min(add(skip(high, p - 1), pl_m), p)
    ph = moving_max(add(skip(low, p - 1), ph_m), p)
    cs = skip(closing, 2 * (p - 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        return multiply_by(divide(subtract(cs, pl), subtract(ph, pl)), 100.0)


def ulcer_index(
    closing: object, period: int = _DEFAULT_ULCER_INDEX_PERIOD
) -> np.ndarray:
    """Ulcer Index ``sqrt(sma(100*(close - max)/max)^2)``; idle = 2*(p-1).

    Forward-port of cinar's exact arithmetic: square the SMA of the
    percentage drawdown (not the SMA of the squared drawdown).
    """
    p = int(period)
    highs = moving_max(closing, p)
    cs = skip(closing, p - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = multiply_by(divide(subtract(cs, highs), highs), 100.0)
        squared_average = pow(sma(drawdown, p), 2)
    return sqrt(squared_average)


def super_trend(
    high: object,
    low: object,
    closing: object,
    period: int = _DEFAULT_SUPER_TREND_PERIOD,
    multiplier: float = _DEFAULT_SUPER_TREND_MULTIPLIER,
) -> np.ndarray:
    """Super Trend over median price +/- multiplier*ATR(HMA smoothed).

    Single series; idle = ATR idle (HMA: ``period + round(sqrt(period)) - 1``).
    Stateful final-band / up-trend recursion, ported exactly.
    """
    p = int(period)
    if p <= 0:
        raise ValueError("period must be greater than 0")
    h = asarray(high)
    l = asarray(low)
    c = asarray(closing)
    n = h.size

    a = _atr(h, l, c, p, hma)
    idle = first_valid(a)
    median = skip(divide_by(add(h, l), 2), idle)
    a_mult = multiply_by(a, multiplier)
    cs = skip(c, idle)

    out = np.full(n, np.nan)
    first = True
    up_trend = False
    previous_closing = 0.0
    final_upper = 0.0
    final_lower = 0.0
    for i in range(idle, n):
        basic_upper = median[i] + a_mult[i]
        basic_lower = median[i] - a_mult[i]
        if first:
            first = False
            final_upper = basic_upper
            final_lower = basic_lower
            st = final_lower
        else:
            if (basic_upper < final_upper) or (previous_closing > final_upper):
                final_upper = basic_upper
            if (basic_lower > final_lower) or (previous_closing < final_lower):
                final_lower = basic_lower
            if up_trend:
                if cs[i] <= final_upper:
                    st = final_upper
                else:
                    st = final_lower
                    up_trend = False
            else:
                if cs[i] >= final_lower:
                    st = final_lower
                else:
                    st = final_upper
                    up_trend = True
        previous_closing = cs[i]
        out[i] = st
    return out