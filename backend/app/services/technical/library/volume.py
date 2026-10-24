"""Volume indicators ported from cinar/indicator.

Port of the ``volume`` package of https://github.com/cinar/indicator
(Cinar Indicator Project, Onur Cinar), licensed under GNU AGPLv3,
Copyright (c) 2021-2026 Onur Cinar.

Every function takes array-like inputs in the same argument order as the Go
source and returns a numpy float64 array of the input length (or a tuple of
arrays for multi-output indicators like KVO).  The leading "idle" positions
that the Go helper streams drop (``Skip``/``IdlePeriod``) are NaN here; the
``_core`` rolling/cumulative primitives reproduce the Go alignment exactly.
"""

from __future__ import annotations

import numpy as np

from ._core import (
    asarray,
    add,
    change,
    change_ratio,
    divide,
    divide_by,
    ema,
    increment_by,
    keep_negatives,
    keep_positives,
    map_previous,
    moving_sum,
    multiply,
    multiply_by,
    pow as _pow,
    shift,
    sign,
    skip,
    sma,
    subtract,
)

# Go Default* constants.
DefaultCmfPeriod = 20
DefaultEmvPeriod = 14
DefaultFiPeriod = 13
DefaultKvoShortPeriod = 34
DefaultKvoLongPeriod = 55
DefaultKvoSignalPeriod = 13
DefaultMfiPeriod = 14
DefaultNviInitial = 1000
DefaultVwapPeriod = 14


def mfm(high, low, closing):
    """Money Flow Multiplier ``((C-L)-(H-C))/(H-L)``.  No idle period."""
    h, l, c = asarray(high), asarray(low), asarray(closing)
    return divide(subtract(subtract(c, l), subtract(h, c)), subtract(h, l))


def mfv(high, low, closing, volume):
    """Money Flow Volume ``MFM * volume``.  No idle period."""
    return multiply(mfm(high, low, closing), volume)


def ad(high, low, closing, volume):
    """Accumulation/Distribution, cumulative sum of MFV.  No idle period.

    Go's ``Ad.Compute`` returns a single series (the cumulative MFV); there is
    no separate signal line in this version of the package.
    """
    return map_previous(lambda prev, cur: prev + cur, mfv(high, low, closing, volume), 0.0)


def obv(closing, volume):
    """On-Balance Volume; adds/subtracts volume on rising/falling close.  No idle period."""
    c, v = asarray(closing), asarray(volume)
    prev = shift(c, 1, fill=0.0)
    delta = np.where(c > prev, v, np.where(c < prev, -v, 0.0))
    return map_previous(lambda prev, cur: prev + cur, delta, 0.0)


def vpt(closing, volume):
    """Volume Price Trend, cumulative ``change_ratio(close) * volume``.  Idle period 1."""
    ratios = multiply(change_ratio(closing, 1), skip(volume, 1))
    return map_previous(lambda prev, cur: prev + cur, ratios, 0.0)


def nvi(closing, volume, initial=DefaultNviInitial):
    """Negative Volume Index; folds volume down days, ``prev*(1+ratio)``.  Idle period 1."""
    closing_ratio = change_ratio(closing, 1)
    volume_change = change(volume, 1)
    flow = multiply(closing_ratio, np.where(volume_change <= 0, 1.0, 0.0))
    return map_previous(lambda prev, cur: prev * (1.0 + cur), flow, float(initial))


def fi(closing, volume, period=DefaultFiPeriod):
    """Force Index ``EMA(period, change(close,1)*volume)``.  Idle period = period."""
    return ema(multiply(change(closing, 1), volume), period)


def emv(high, low, volume, period=DefaultEmvPeriod):
    """Ease of Movement ``SMA(period, (change(midpoint,1))/((v/1e8)/(H-L)))``.  Idle period = period."""
    distance = change(divide_by(add(high, low), 2), 1)
    box_ratio = divide(divide_by(volume, 100000000.0), subtract(high, low))
    return sma(divide(distance, box_ratio), period)


def mfi(high, low, closing, volume, period=DefaultMfiPeriod):
    """Money Flow Index ``100 - 100/(1 + sumPos/sumNeg)`` over *period*.  Idle period = period."""
    tp = divide_by(add(add(high, low), closing), 3)
    raw = multiply(tp, volume)
    flow = multiply(sign(change(tp, 1)), skip(raw, 1))
    ratio = divide(moving_sum(keep_positives(flow), period),
                   moving_sum(multiply_by(keep_negatives(flow), -1), period))
    return increment_by(multiply_by(_pow(increment_by(ratio, 1), -1), -100), 100)


def cmf(high, low, closing, volume, period=DefaultCmfPeriod):
    """Chaikin Money Flow ``sum(mfv, period)/sum(volume, period)``.  Idle period = period-1."""
    return divide(moving_sum(mfv(high, low, closing, volume), period),
                  moving_sum(volume, period))


def vwap(closing, volume, period=DefaultVwapPeriod):
    """Volume Weighted Average Price ``sum(C*V, period)/sum(V, period)``.  Idle period = period-1."""
    return divide(moving_sum(multiply(closing, volume), period), moving_sum(volume, period))


def kvo(high, low, volume, short_period=DefaultKvoShortPeriod,
        long_period=DefaultKvoLongPeriod, signal_period=DefaultKvoSignalPeriod):
    """Klinger Volume Oscillator, returns ``(kvo, signal)``.  Idle period = long+signal.

    ``trend = +1 if H>H[1] and L>=L[1]; -1 if H<=H[1] and L<L[1]; else 0``,
    ``VF = volume*trend``, ``kvo = EMA(VF,short) - EMA(VF,long)`` (both EMAs
    aligned at *long_period*), ``signal = EMA(kvo, signal_period)``.
    """
    h, l, v = asarray(high), asarray(low), asarray(volume)
    prev_h = shift(h, 1, fill=0.0)
    prev_l = shift(l, 1, fill=0.0)
    trend = np.where((h > prev_h) & (l >= prev_l), 1.0,
                     np.where((h <= prev_h) & (l < prev_l), -1.0, 0.0))
    vf = skip(multiply(v, trend), 1)
    short_raw = ema(vf, short_period)
    long_ema = ema(vf, long_period)
    short_ema = skip(short_raw, (long_period - 1) - (short_period - 1))
    kvo = subtract(short_ema, long_ema)
    signal = ema(kvo, signal_period)
    kvo_result = skip(kvo, signal_period - 1)
    return kvo_result, signal