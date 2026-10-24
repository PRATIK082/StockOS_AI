"""Trend-family technical indicators (numpy port).

Faithful port of the ``trend`` package of the Cinar Indicator Project:

    https://github.com/cinar/indicator
    Copyright (c) 2021-2026 Onur Cinar, licensed under GNU AGPLv3
    https://github.com/cinar/indicator/blob/master/LICENSE

All functions follow the same-library conventions used by ``_core``: inputs are
array-like floats in the same argument order as the Go ``Compute`` methods,
outputs are same-length ``numpy.ndarray`` (or tuples of arrays) with leading
"idle" positions set to ``NaN``. Formulas, defaults and idle periods match the
Go implementation exactly (including nonstandard variants such as AR<LL> Aroon
partial windows, DPO's SkipLast lag, and ROC's zero-price -> 0.0 rule).

The moving-average overlays (SMA/EMA/RMA/SMMA/WMA/DEMA/TEMA/HMA/KAMA/TRIMA,
moving min/max/sum, generic stochastic) live in ``_core`` and are re-exported
here to mirror the cinar layout where they belong to the ``trend`` package.
"""

from __future__ import annotations

import math

import numpy as np

from ._core import (
    asarray,
    first_valid,
    moving_max,
    moving_min,
    moving_sum,
    sma,
    ema,
    rma,
    smma,
    wma,
    dema,
    tema,
    hma,
    kama,
    trima,
    stochastic,
    add,
    subtract,
    multiply,
    divide,
    multiply_by,
    divide_by,
    increment_by,
    shift,
    skip,
    skip_last,
    change,
    change_ratio,
)

# --------------------------------------------------------------------------- #
# Re-export of the overlay builders (mirror of cinar where they live in trend).
# --------------------------------------------------------------------------- #

__all__ = [
    "sma", "ema", "rma", "smma", "wma", "dema", "tema", "hma", "kama", "trima",
    "moving_sum", "moving_max", "moving_min", "stochastic",
    "typical_price", "weighted_close", "bop", "roc", "slope", "vwma", "cci",
    "apo", "macd", "mass_index", "mcginley_dynamic", "aroon", "kdj", "kst",
    "stc", "t3", "trix", "tsi", "dpo", "cfo", "mlr", "mls", "envelope",
    "slow_stochastic", "pivot_point",
]


def _since_scan(window: np.ndarray) -> int:
    """Count periods since the most recent max within a window.

    Mirrors ``helper.MaxSince``/``helper.MinSince``: scan newest-first,
    counting until the first max is seen and then a strictly smaller (or
    larger for min) value. ``since - 1`` is the returned lag.
    """
    m = float(np.max(window))
    since = 0
    found = False
    for k in range(window.size - 1, -1, -1):
        n = float(window[k])
        if found and n < m:
            break
        since += 1
        if n == m:
            found = True
    return since - 1


def _max_since(values: np.ndarray, first: int, period: int) -> np.ndarray:
    """Periods since the most recent rolling max, per input index."""
    n = values.size
    out = np.full(n, np.nan)
    for i in range(first, n):
        start = max(first, i - period + 1)
        out[i] = _since_scan(values[start : i + 1])
    return out


def typical_price(high, low, closing) -> np.ndarray:
    """Typical Price ``(High + Low + Closing) / 3`` (idle 0)."""
    return divide_by(add(add(high, low), closing), 3)


def weighted_close(high, low, closing) -> np.ndarray:
    """Weighted Close ``(High + Low + 2*Closing) / 4`` (idle 0)."""
    h = asarray(high)
    l = asarray(low)
    c = asarray(closing)
    return (h + l + 2 * c) / 4.0


def bop(opening, high, low, closing) -> np.ndarray:
    """Balance of Power ``(Closing - Opening) / (High - Low)`` (idle 0)."""
    return divide(subtract(closing, opening), subtract(high, low))


def roc(values, period: int = 9) -> np.ndarray:
    """Rate of Change ``(value - value_n_ago) / value_n_ago`` (idle period).

    When the base price is zero cinar emits 0.0 (division skipped); mirrored
    here (the value stays 0.0 rather than inf/nan).
    """
    if period <= 0:
        period = 9
    arr = asarray(values)
    n = arr.size
    out = np.full(n, np.nan)
    if n > period:
        base = arr[: n - period]
        ch = arr[period:] - base
        with np.errstate(divide="ignore", invalid="ignore"):
            out[period:] = np.divide(ch, base, out=np.zeros_like(ch), where=base != 0)
    return out


def slope(values, period: int = 14) -> np.ndarray:
    """Rate of change slope ``Change(values, period) / period`` (idle period)."""
    if period <= 0:
        period = 14
    return divide_by(change(values, period), period)


def vwma(closing, volume, period: int = 20) -> np.ndarray:
    """Volume Weighted Moving Average ``Sum(Close*Vol)/Sum(Vol)`` (idle p-1)."""
    c = asarray(closing)
    v = asarray(volume)
    return divide(moving_sum(multiply(c, v), period), moving_sum(v, period))


def cci(high, low, closing, period: int = 20) -> np.ndarray:
    """Commodity Channel Index (idle 2*period-2).

    ``ma = SMA(typical price, period)``, ``meanDev = SMA(|TP - ma|, period)``,
    ``CI = (TP - ma) / (0.015 * meanDev)``.
    """
    tp = typical_price(high, low, closing)
    ma = sma(tp, period)
    mean_dev = sma(np.abs(subtract(tp, ma)), period)
    return divide(subtract(tp, ma), multiply_by(mean_dev, 0.015))


def apo(values, fast_period: int = 14, slow_period: int = 30,
        smoothing: float = 2.0) -> np.ndarray:
    """Absolute Price Oscillator ``EMA(fast) - EMA(slow)`` (idle slow-1)."""
    return subtract(ema(values, fast_period, smoothing), ema(values, slow_period, smoothing))


def macd(values, period1: int = 12, period2: int = 26,
         period3: int = 9) -> tuple[np.ndarray, np.ndarray]:
    """Moving Average Convergence Divergence, returns ``(MACD, signal)``.

    ``macd = EMA(p1) - EMA(p2)``, ``signal = EMA(macd, p3)``. MACD output is
    idle ``period2 + period3 - 2``.
    """
    raw = subtract(ema(values, period1), ema(values, period2))
    return skip(raw, period3 - 1), ema(raw, period3)


def mass_index(highs, lows, period1: int = 9, period2: int = 9,
               period3: int = 25) -> np.ndarray:
    """Mass Index ``Sum(EMA1(high-low)/EMA2(EMA1), period3)`` (idle p1+p2+p3-3)."""
    ema1 = ema(subtract(highs, lows), period1)
    ratio = divide(ema1, ema(ema1, period2))
    return moving_sum(ratio, period3)


def mcginley_dynamic(values, period: int = 14) -> np.ndarray:
    """McGinley Dynamic (idle 0), recursive:

    ``MD = MD_prev + (Close - MD_prev) / (period * (Close/MD_prev)^4)``
    """
    arr = asarray(values)
    n = arr.size
    out = np.full(n, np.nan)
    start = first_valid(arr)
    if start >= n:
        return out
    before = float(arr[start])
    out[start] = before
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        for i in range(start + 1, n):
            val = float(arr[i])
            if before == 0:
                before = val
            else:
                ratio = val / before
                before = before + (val - before) / (period * ratio ** 4)
            out[i] = before
    return out


def aroon(high, low, period: int = 25) -> tuple[np.ndarray, np.ndarray]:
    """Aroon Up / Aroon Down, returns ``(aroonUp, aroonDown)`` (idle period-1).

    Uses the cinar partial-window ``MaxSince``/``MinSince`` semantics over the
    rolling max/min streams and rounds each result to 0 decimals.
    """
    mx = moving_max(high, period)
    mn = moving_min(low, period)
    first = period - 1
    since_high = _max_since(mx, first, period)
    since_low = _min_since_low(mn, first, period)
    up = np.round(divide_by(increment_by(multiply_by(since_high, -1), period), period) * 100.0, 0)
    down = np.round(divide_by(increment_by(multiply_by(since_low, -1), period), period) * 100.0, 0)
    return up, down


def _min_since_low(values: np.ndarray, first: int, period: int) -> np.ndarray:
    """Periods since the most recent rolling min, per input index."""
    n = values.size
    out = np.full(n, np.nan)
    for i in range(first, n):
        start = max(first, i - period + 1)
        window = values[start : i + 1]
        m = float(np.min(window))
        since = 0
        found = False
        for k in range(window.size - 1, -1, -1):
            x = float(window[k])
            if found and x > m:
                break
            since += 1
            if x == m:
                found = True
        out[i] = since - 1
    return out


def kdj(high, low, closing, period: int = 9, k_period: int = 3,
        d_period: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """KDJ returns ``(K, D, J)`` (idle period + k_period + d_period - 3).

    ``RSV = 100*(C - Min(L, period)) / (Max(H, period) - Min(L, period))``,
    ``K = SMA(RSV, k_period)``, ``D = SMA(K, d_period)``, ``J = 3K - 2D``.
    """
    mn = moving_min(low, period)
    mx = moving_max(high, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsv = multiply_by(divide(subtract(closing, mn), subtract(mx, mn)), 100)
    k = sma(rsv, k_period)
    d = sma(k, d_period)
    j = subtract(multiply_by(k, 3), multiply_by(d, 2))
    return k, d, j


def kst(values, roc_period1: int = 10, roc_period2: int = 15,
        roc_period3: int = 20, roc_period4: int = 30,
        sma_period1: int = 10, sma_period2: int = 10, sma_period3: int = 10,
        sma_period4: int = 15, signal_period: int = 9) -> tuple[np.ndarray, np.ndarray]:
    """Know Sure Thing ``(KST, signal)``.

    ``RCMA_i = SMA(ROC(values, roc_period_i), sma_period_i)``;
    ``KST = RCMA1 + 2*RCMA2 + 3*RCMA3 + 4*RCMA4``;
    ``signal = SMA(KST, signal_period)``.
    """
    roc_periods = [roc_period1, roc_period2, roc_period3, roc_period4]
    sma_periods = [sma_period1, sma_period2, sma_period3, sma_period4]
    weights = [1, 2, 3, 4]
    rcma = []
    for rp, sp in zip(roc_periods, sma_periods):
        rcma.append(sma(roc(values, rp), sp))
    kst_ = multiply_by(rcma[0], weights[0])
    for r, wv in zip(rcma[1:], weights[1:]):
        kst_ = add(kst_, multiply_by(r, wv))
    return skip(kst_, signal_period - 1), sma(kst_, signal_period)


def stc(values, fast_period: int = 23, slow_period: int = 50,
        k_period: int = 10, d_period: int = 3) -> np.ndarray:
    """Schaff Trend Cycle (idle slow-1 + k_period + d_period - 2)."""
    macd_ = subtract(ema(values, fast_period), ema(values, slow_period))
    k, d = stochastic(macd_, k_period, d_period)
    return multiply_by(divide(subtract(macd_, k), subtract(d, k)), 100)


def t3(values, period: int = 5, volume_factor: float = 0.7) -> np.ndarray:
    """Tillson T3 moving average ``c1*E6 + c2*E5 + c3*E4 + c4*E3`` (idle 6p-6).

    ``E_n`` = n-th chained EMA(period); with ``a = volume_factor``:
    ``c1 = -a^3, c2 = 3a^2, c3 = -3a, c4 = a^3``.
    """
    a = float(volume_factor)
    c1, c2, c3, c4 = -a ** 3, 3 * a ** 2, -3 * a, a ** 3
    e1 = ema(values, period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    e4 = ema(e3, period)
    e5 = ema(e4, period)
    e6 = ema(e5, period)
    return add(add(multiply_by(e6, c1), multiply_by(e5, c2)),
               add(multiply_by(e4, c3), multiply_by(e3, c4)))


def trix(values, period: int = 15) -> np.ndarray:
    """Triple Exponential Average ``ChangeRatio(EMA(EMA(EMA)), 1)`` (idle 3p-2)."""
    e1 = ema(values, period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    return change_ratio(e3, 1)


def tsi(values, first_smoothing_period: int = 25,
        second_smoothing_period: int = 13) -> np.ndarray:
    """True Strength Index ``100 * PCDS / APCDS`` (idle p1+p2-1)."""
    diff = change(values, 1)
    pcds = ema(ema(diff, second_smoothing_period), first_smoothing_period)
    apcds = ema(ema(np.abs(diff), second_smoothing_period), first_smoothing_period)
    return multiply_by(divide(pcds, apcds), 100)


def dpo(values, period: int = 20) -> np.ndarray:
    """Detrended Price Oscillator (idle ``period - 1 + period//2 + 1``).

    ``k = period//2 + 1``; ``DPO[i] = Price[i] - SMA(price, period)[i - k]`` for
    ``i >= idle`` (mirrors cinar's Shift + SkipLast alignment).
    """
    if period <= 1:
        period = 20
    k = period // 2 + 1
    idle = (period - 1) + k
    s = sma(values, period)
    shifted = shift(s, k, fill=np.nan)
    return skip(subtract(values, shifted), idle)


def mls(x, y, period: int) -> tuple[np.ndarray, np.ndarray]:
    """Moving Least Squares, returns ``(slope, intercept)`` (idle period-1).

    ``m = (p*sumXY - sumX*sumY) / (p*sumX2 - sumX*sumX)``;
    ``b = (sumY - m*sumX) / p`` over each window.
    """
    x = asarray(x)
    y = asarray(y)
    n = x.size
    sum_x = moving_sum(x, period)
    sum_x2 = moving_sum(x * x, period)
    sum_y = moving_sum(y, period)
    sum_xy = moving_sum(x * y, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        m = divide(subtract(multiply_by(sum_xy, period), multiply(sum_x, sum_y)),
                   subtract(multiply_by(sum_x2, period), multiply(sum_x, sum_x)))
        b = divide_by(subtract(sum_y, multiply(m, sum_x)), period)
    return m, b


def mlr(x, y, period: int) -> np.ndarray:
    """Moving Linear Regression ``r = m*x + b`` of y on x (idle period-1)."""
    m, b = mls(x, y, period)
    return add(multiply(m, x), b)


def cfo(values, period: int = 14) -> np.ndarray:
    """Chande Forecast Oscillator ``((Price - Forecast)/Price)*100`` (idle p-1)."""
    n = len(values)
    x = np.arange(n, dtype=np.float64)
    forecast = mlr(x, values, period)
    closing = asarray(values)
    return multiply_by(divide(subtract(closing, forecast), closing), 100)


def envelope(closings, period: int = 20, percentage: float = 20.0,
             ma=None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Envelope bands, returns ``(upper, middle, lower)`` (idle = MA idle).

    ``upper = middle * (1 + percentage/100)``,
    ``lower = middle * (1 - percentage/100)``. ``ma`` defaults to SMA; pass
    e.g. ``ema`` for the EMA variant.
    """
    if ma is None:
        middle = sma(closings, period)
    else:
        middle = ma(closings, period)
    upper = multiply_by(middle, 1 + percentage / 100.0)
    lower = multiply_by(middle, 1 - percentage / 100.0)
    return upper, middle, lower


def slow_stochastic(values, period: int = 10, k_period: int = 3,
                    d_period: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Slow Stochastic over a single series, returns ``(slow %K, slow %D)``.

    ``Fast %K = Stochastic(values, period)`` (as percentage) then
    ``Slow %K = SMA(Fast %K, k_period)``, ``Slow %D = SMA(Slow %K, d_period)``.
    Idle ``period + k_period + d_period - 3``.
    """
    mn = moving_min(values, period)
    mx = moving_max(values, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        fast_k = multiply_by(divide(subtract(values, mn), subtract(mx, mn)), 100)
    slow_k = sma(fast_k, k_period)
    slow_d = sma(slow_k, d_period)
    return skip(slow_k, d_period - 1), slow_d


def pivot_point(opens, highs, lows, closings, method: str = "standard") -> dict:
    """Pivot Points from the previous period, returns a dict of arrays.

    Keys: ``P, R1, R2, R3, R4, S1, S2, S3, S4``, each a same-length array,
    idle 1 (the first row has no previous period). ``method`` one of
    ``standard`` (default), ``woodie``, ``camarilla``, ``fibonacci``.
    """
    opens = asarray(opens)
    highs = asarray(highs)
    lows = asarray(lows)
    closings = asarray(closings)
    n = opens.size
    keys = ["P", "R1", "R2", "R3", "R4", "S1", "S2", "S3", "S4"]
    res = {k: np.full(n, np.nan) for k in keys}

    method_l = method.lower()
    for i in range(1, n):
        h = float(highs[i - 1])
        l = float(lows[i - 1])
        c = float(closings[i - 1])
        o = float(opens[i])
        d = h - l
        if method_l == "standard":
            p = (h + l + c) / 3
            r1, s1 = 2 * p - l, 2 * p - h
            r2, s2 = p + d, p - d
            r3, s3 = h + 2 * (p - l), l - 2 * (h - p)
            r4, s4 = h + 3 * (p - l), l - 3 * (h - p)
        elif method_l == "woodie":
            p = (h + l + 2 * o) / 4
            r1, s1 = 2 * p - l, 2 * p - h
            r2, s2 = p + d, p - d
            r3, s3 = h + 2 * (p - l), l - 2 * (p - l)
            r4 = s4 = np.nan
        elif method_l == "camarilla":
            p = (h + l + c) / 3
            r1, r2, r3, r4 = c + d * 1.1 / 12, c + d * 1.1 / 6, c + d * 1.1 / 4, c + d * 1.1 / 2
            s1, s2, s3, s4 = c - d * 1.1 / 12, c - d * 1.1 / 6, c - d * 1.1 / 4, c - d * 1.1 / 2
        elif method_l == "fibonacci":
            p = (h + l + c) / 3
            r1, s1 = p + d * 0.382, p - d * 0.382
            r2, s2 = p + d * 0.618, p - d * 0.618
            r3, s3 = p + d * 1.0, p - d * 1.0
            r4 = s4 = np.nan
        else:
            raise ValueError(f"unknown pivot point method: {method}")
        res["P"][i] = p
        res["R1"][i] = r1
        res["R2"][i] = r2
        res["R3"][i] = r3
        res["R4"][i] = r4
        res["S1"][i] = s1
        res["S2"][i] = s2
        res["S3"][i] = s3
        res["S4"][i] = s4
    return res