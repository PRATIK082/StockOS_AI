"""Momentum indicators â€” faithful numpy port of https://github.com/cinar/indicator.

Port of the ``momentum`` package of the Cinar Indicator Project (Onur Cinar),
GNU AGPLv3, copyright 2021-2026 Onur Cinar.
https://github.com/cinar/indicator/blob/master/LICENSE

Each function mirrors the exact math of the matching Go file (argument order,
period defaults, scalings and idle alignment). Inputs are array-like scalars
in the same order as the Go ``Compute`` signature; every output is a 1-D
``numpy.ndarray`` of ``float64`` with the same length as the inputs (or a
tuple of such arrays for multi-output indicators). Leading idle positions that
the Go code drops via ``helper.Skip`` / ``IdlePeriod`` are ``np.nan``; the
shared ``_core`` primitives treat a leading NaN block as "data starts at the
first non-NaN index" so stream alignment is reproduced exactly.
"""

from __future__ import annotations

import numpy as np

from ._core import (
    add,
    asarray,
    change,
    decrement_by,
    divide,
    divide_by,
    first_valid,
    increment_by,
    keep_negatives,
    keep_positives,
    map_previous,
    moving_max,
    moving_min,
    moving_sum,
    multiply,
    multiply_by,
    pow as _pow,
    rma,
    shift,
    skip,
    skip_last,
    sma,
    subtract,
    wma,
)

__all__ = [
    "awesome_oscillator",
    "chaikin_oscillator",
    "connors_rsi",
    "coppock_curve",
    "elder_ray",
    "fisher",
    "ibs",
    "ichimoku_cloud",
    "ppo",
    "prings_special_k",
    "pvo",
    "qstick",
    "rsi",
    "rvi",
    "stochastic_oscillator",
    "stochastic_rsi",
    "td_sequential",
    "ultimate_oscillator",
    "williams_r",
]


def _roc(a, period):
    """Rate of change ``(v - v[n-ago]) / v[n-ago]``; idle = *period*."""
    arr = asarray(a)
    prev = shift(arr, period, fill=np.nan)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        out = change(arr, period) / prev
    return np.where(prev == 0.0, 0.0, out)


def _percent_rank(a, period):
    """Percentile rank of each value vs. the previous *period*-1 values (0-100).

    Mirrors ``helper.PercentRank``; idle = *period* values past the stream
    start.
    """
    arr = asarray(a)
    if period <= 1:
        return np.full(arr.size, np.nan)
    out = np.full(arr.size, np.nan)
    start = first_valid(arr)
    for i in range(start + period, arr.size):
        window = arr[i - period + 1 : i]
        if np.isnan(window).any():
            continue
        out[i] = 100.0 * np.count_nonzero(window < arr[i]) / (period - 1)
    return out


def _ema(a, period, smoothing=2.0):
    """Exponential moving average, SMA-seeded recurrence (mirror of trend.Ema)."""
    arr = asarray(a)
    start = first_valid(arr)
    n = arr.size
    out = np.full(n, np.nan)
    if n - start < period:
        return out
    dense = arr[start:]
    prev = float(np.mean(dense[:period]))
    first = start + period - 1
    out[first] = prev
    multiplier = smoothing / (period + 1)
    for i in range(period, dense.size):
        prev = (dense[i] - prev) * multiplier + prev
        out[start + i] = prev
    return out


def _skip_stream(a, count):
    """Drop the first *count* emitted outputs of a stream.

    The stream starts at its first non-NaN index, mirroring ``helper.Skip``
    applied to the emitted channel of a compositor.
    """
    arr = asarray(a)
    return skip(arr, first_valid(arr) + int(count))


def rsi(closings, period=14):
    """Relative Strength Index 100 - 100/(1+RS); idle = *period*."""
    closes = asarray(closings)
    changes = change(closes, 1)
    average_gains = rma(keep_positives(changes), period)
    average_losses = multiply_by(rma(keep_negatives(changes), period), -1)
    rs = divide(average_gains, average_losses)
    return increment_by(multiply_by(_pow(increment_by(rs, 1), -1), -100), 100)


def awesome_oscillator(highs, lows, short_period=5, long_period=34):
    """Awesome Oscillator, SMA(median, short) - SMA(median, long)."""
    median = divide_by(add(highs, lows), 2)
    short_sma = _skip_stream(sma(median, short_period), long_period - short_period)
    return subtract(short_sma, sma(median, long_period))


def chaikin_oscillator(highs, lows, closings, volumes, short_period=3, long_period=10):
    """Chaikin Oscillator ``(co, ad)``; EMA(short,AD) - EMA(long,AD)."""
    h = asarray(highs)
    l = asarray(lows)
    c = asarray(closings)
    with np.errstate(divide="ignore", invalid="ignore"):
        mfm = divide(subtract(subtract(c, l), subtract(h, c)), subtract(h, l))
    mfv = multiply(mfm, asarray(volumes))
    ad = map_previous(lambda prev, cur: prev + cur, mfv, 0.0)
    short_ema = _skip_stream(_ema(ad, short_period), long_period - short_period)
    co = subtract(short_ema, _ema(ad, long_period))
    return co, skip(ad, long_period - 1)


def connors_rsi(closings, rsi_period=3, streak_rsi_period=2, percent_rank_period=100):
    """Connors RSI, mean of RSI(close), RSI(streak) and PercentRank(ROC)."""
    closes = asarray(closings)
    rsis = rsi(closes, rsi_period)

    changes = change(closes, 1)
    with np.errstate(invalid="ignore"):
        direction = np.where(
            np.isnan(changes),
            np.nan,
            np.where(changes > 0, 1.0, np.where(changes < 0, -1.0, 0.0)),
        )

    def _streak_step(prev, curr):
        if curr > 0:
            return prev + 1.0 if prev > 0 else 1.0
        if curr < 0:
            return prev - 1.0 if prev < 0 else -1.0
        return 0.0

    streaks = map_previous(_streak_step, direction, 0.0)
    streak_rsis = rsi(streaks, streak_rsi_period)
    percent_ranks = _percent_rank(_roc(closes, 1), percent_rank_period)

    return divide_by(add(add(rsis, streak_rsis), percent_ranks), 3)


def coppock_curve(closings, roc_period1=14, roc_period2=11, wma_period=10):
    """Coppock Curve, WMA(ROC(roc1)*100 + ROC(roc2)*100, wma)."""
    closes = asarray(closings)
    max_roc = max(roc_period1, roc_period2)
    roc1 = _skip_stream(multiply_by(_roc(closes, roc_period1), 100), max_roc - roc_period1)
    roc2 = _skip_stream(multiply_by(_roc(closes, roc_period2), 100), max_roc - roc_period2)
    return wma(add(roc1, roc2), wma_period)


def elder_ray(highs, lows, closings, period=13):
    """Elder-Ray Index ``(bull_power, bear_power)``."""
    ema_closes = _ema(closings, period)
    bull_power = subtract(skip(highs, period - 1), ema_closes)
    bear_power = subtract(skip(lows, period - 1), ema_closes)
    return bull_power, bear_power


def fisher(closings, period=10):
    """Fisher Transform, clamped ``0.5 * ln((1+x)/(1-x))``; idle = *period*-1."""
    closes = asarray(closings)
    mn = moving_min(closes, period)
    mx = moving_max(closes, period)
    normalized = divide(subtract(skip(closes, period - 1), mn), subtract(mx, mn))
    x = decrement_by(multiply_by(normalized, 2), 1)
    clamp_x = np.where(x > 0.999, 0.999, np.where(x < -0.999, -0.999, x))
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        log_term = np.log(
            divide(
                increment_by(clamp_x, 1),
                increment_by(multiply_by(clamp_x, -1), 1),
            )
        )
    return multiply_by(log_term, 0.5)


def ibs(highs, lows, closings):
    """Internal Bar Strength ``(close - low) / (high - low)``, 0 if flat bar."""
    h = asarray(highs)
    l = asarray(lows)
    denom = subtract(h, l)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = divide(subtract(asarray(closings), l), denom)
    return np.where(denom == 0.0, 0.0, result)


def ichimoku_cloud(
    highs,
    lows,
    closings,
    conversion_period=9,
    base_period=26,
    leading_period=52,
    lagging_period=26,
):
    """Ichimoku Cloud ``(conversion, base, senkou_a, senkou_b, chikou)``."""
    h = asarray(highs)
    l = asarray(lows)
    c = asarray(closings)

    conversion = divide_by(add(moving_max(h, conversion_period), moving_min(l, conversion_period)), 2)
    base = divide_by(add(moving_max(h, base_period), moving_min(l, base_period)), 2)
    senkou_b = divide_by(add(moving_max(h, leading_period), moving_min(l, leading_period)), 2)

    conversion = _skip_stream(conversion, base_period - conversion_period)
    senkou_a = divide_by(add(conversion, base), 2)
    senkou_a = _skip_stream(senkou_a, leading_period - base_period)
    conversion = _skip_stream(conversion, leading_period - base_period)
    base = _skip_stream(base, leading_period - base_period)

    chikou = shift(c, lagging_period, 0)
    chikou = skip(chikou, leading_period - 1)
    chikou = skip_last(chikou, lagging_period)

    return conversion, base, senkou_a, senkou_b, chikou


def _pvo_like(values, short_period, long_period, signal_period):
    vals = asarray(values)
    short_ema = _skip_stream(_ema(vals, short_period), long_period - short_period)
    long_ema = _ema(vals, long_period)
    osc = multiply_by(divide(subtract(short_ema, long_ema), long_ema), 100)
    signal = _ema(osc, signal_period)
    osc = _skip_stream(osc, signal_period - 1)
    histogram = subtract(osc, signal)
    return osc, signal, histogram


def ppo(closings, short_period=12, long_period=26, signal_period=9):
    """Percentage Price Oscillator ``(ppo, signal, histogram)``."""
    return _pvo_like(closings, short_period, long_period, signal_period)


def pvo(volumes, short_period=12, long_period=26, signal_period=9):
    """Percentage Volume Oscillator ``(pvo, signal, histogram)``."""
    return _pvo_like(volumes, short_period, long_period, signal_period)


def prings_special_k(closings):
    """Prings Special K, weighted sum of 12 ROC-SMA branches aligned to 724."""
    closes = asarray(closings)
    rocs = {p: _roc(closes, p) for p in (10, 15, 20, 30, 40, 65, 75, 100, 195, 265, 390, 530)}
    branches = [
        (10, sma(rocs[10], 10)),
        (15, sma(rocs[15], 10)),
        (20, sma(rocs[20], 10)),
        (30, sma(rocs[30], 15)),
        (40, sma(rocs[40], 50)),
        (65, sma(rocs[65], 65)),
        (75, sma(rocs[75], 75)),
        (100, sma(rocs[100], 100)),
        (195, sma(rocs[195], 130)),
        (265, sma(rocs[265], 130)),
        (390, sma(rocs[390], 130)),
        (530, sma(rocs[530], 195)),
    ]
    max_idle = 194 + 530
    sma_periods = (10, 10, 10, 15, 50, 65, 75, 100, 130, 130, 130, 195)
    acc = None
    for (roc_period, branch), sma_period, weight in zip(
        branches,
        sma_periods,
        (1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4),
    ):
        branch = _skip_stream(branch, max_idle - (sma_period - 1) - roc_period)
        term = multiply_by(branch, weight)
        acc = term if acc is None else add(acc, term)
    return acc


def qstick(openings, closings, period=20):
    """Qstick, SMA(closing - opening)."""
    return sma(subtract(closings, openings), period)


def rvi(opens, highs, lows, closings, period=10, signal_period=4):
    """Relative Vigor Index ``(rvi, signal)`` with a 1-2-2-1 FIR filter."""

    def _fir(a):
        filtered = divide_by(
            add(
                add(a, multiply_by(shift(a, 1), 2)),
                add(multiply_by(shift(a, 2), 2), shift(a, 3)),
            ),
            6,
        )
        return skip(filtered, 3)

    numerator = subtract(closings, opens)
    denominator = subtract(highs, lows)
    sma_num = sma(_fir(numerator), period)
    sma_den = sma(_fir(denominator), period)
    rvi_value = divide(sma_num, sma_den)
    signal = sma(rvi_value, signal_period)
    return _skip_stream(rvi_value, signal_period - 1), signal


def stochastic_oscillator(highs, lows, closings, max_and_min_period=14, period=3):
    """Stochastic Oscillator ``(k, d)`` of the high-low-close range."""
    lowest = moving_min(lows, max_and_min_period)
    highest = moving_max(highs, max_and_min_period)
    closes = skip(asarray(closings), max_and_min_period - 1)
    k = multiply_by(divide(subtract(closes, lowest), subtract(highest, lowest)), 100)
    d = sma(k, period)
    return _skip_stream(k, period - 1), d


def stochastic_rsi(closings, period=14):
    """Stochastic RSI over RSI values; idle = 2*period - 1."""
    rsis = rsi(closings, period)
    shifted = _skip_stream(rsis, period - 1)
    mn = moving_min(rsis, period)
    mx = moving_max(rsis, period)
    return divide(subtract(shifted, mn), subtract(mx, mn))


def td_sequential(
    closings,
    lookback=4,
    countdown_lookback=2,
    setup_period=9,
    countdown_period=13,
):
    """TD Sequential ``(buy_setup, sell_setup, buy_countdown, sell_countdown)``."""
    closes = asarray(closings)
    n = closes.size
    buy_setup = np.zeros(n)
    sell_setup = np.zeros(n)
    buy_countdown = np.zeros(n)
    sell_countdown = np.zeros(n)

    cur_buy_setup = 0.0
    cur_sell_setup = 0.0
    buy_countdown_count = 0
    sell_countdown_count = 0
    in_buy_countdown = False
    in_sell_countdown = False
    close_history = []

    for i in range(n):
        current = float(closes[i])
        close_history.append(current)
        if len(close_history) <= lookback:
            continue

        prev_close = close_history[len(close_history) - 1 - lookback]

        if current < prev_close:
            cur_buy_setup = (cur_buy_setup + 1.0) if cur_buy_setup >= 0 else 1.0
        else:
            cur_buy_setup = 0.0
        if current > prev_close:
            cur_sell_setup = (cur_sell_setup - 1.0) if cur_sell_setup <= 0 else -1.0
        else:
            cur_sell_setup = 0.0

        if cur_buy_setup >= float(setup_period):
            in_buy_countdown = True
        if cur_sell_setup <= -float(setup_period):
            in_sell_countdown = True

        if in_buy_countdown and buy_countdown_count < countdown_period and len(close_history) > countdown_lookback:
            if current <= close_history[len(close_history) - 1 - countdown_lookback]:
                buy_countdown_count += 1
        if in_sell_countdown and sell_countdown_count < countdown_period and len(close_history) > countdown_lookback:
            if current >= close_history[len(close_history) - 1 - countdown_lookback]:
                sell_countdown_count += 1

        if buy_countdown_count >= countdown_period:
            buy_countdown_count = 0
            in_buy_countdown = False
        if sell_countdown_count >= countdown_period:
            sell_countdown_count = 0
            in_sell_countdown = False

        buy_setup[i] = cur_buy_setup
        sell_setup[i] = cur_sell_setup
        buy_countdown[i] = buy_countdown_count
        sell_countdown[i] = sell_countdown_count

    return buy_setup, sell_setup, buy_countdown, sell_countdown


def ultimate_oscillator(highs, lows, closings, short_period=7, medium_period=14, long_period=28):
    """Ultimate Oscillator, weighted average of 7/14/28-period BP/TR sums."""
    h = asarray(highs)
    l = asarray(lows)
    c = asarray(closings)
    prior = shift(c, 1, 0.0)
    cur = skip(c, 1)
    hs = skip(h, 1)
    ls = skip(l, 1)
    min_low_pc = np.minimum(ls, prior)
    max_high_pc = np.maximum(hs, prior)
    bp = subtract(cur, min_low_pc)
    tr = subtract(max_high_pc, min_low_pc)

    short_bp = _skip_stream(moving_sum(bp, short_period), long_period - short_period)
    short_tr = _skip_stream(moving_sum(tr, short_period), long_period - short_period)
    medium_bp = _skip_stream(moving_sum(bp, medium_period), long_period - medium_period)
    medium_tr = _skip_stream(moving_sum(tr, medium_period), long_period - medium_period)
    long_bp = moving_sum(bp, long_period)
    long_tr = moving_sum(tr, long_period)

    avg_short = divide(short_bp, short_tr)
    avg_medium = divide(medium_bp, medium_tr)
    avg_long = divide(long_bp, long_tr)

    return divide_by(multiply_by(add(add(multiply_by(avg_short, 4), multiply_by(avg_medium, 2)), avg_long), 100), 7)


def williams_r(highs, lows, closings, period=14):
    """Williams %R, (highest - close)/(highest - lowest) * -100."""
    highest = moving_max(highs, period)
    lowest = moving_min(lows, period)
    closes = skip(asarray(closings), period - 1)
    return multiply_by(divide(subtract(highest, closes), subtract(highest, lowest)), -100)
