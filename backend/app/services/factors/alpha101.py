"""Kakushadze (2015) "101 Formulaic Alphas" — vectorized, look-ahead-free.

Each alpha is a pure function of the precomputed context ``Ctx`` built from an
OHLCV DataFrame. Conventions follow the standard single-symbol translation:

* ``rank(x)`` ranks the series' own history (percentile) — see operators.
* ``indneutralize`` has no industry map here, so it is the documented identity
  (factors that would neutralize against sectors degrade gracefully, never
  fabricate a classification).
* ``cap`` (alpha 056) is substituted with ``adv20`` (average daily dollar
  volume) since market cap is not in the OHLCV feed — disclosed per factor.
* ``vwap`` is estimated as typical price ``(high+low+close)/3``.
* ``returns`` = close-to-close daily returns.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.services.factors.operators import (
    abs_,
    correlation,
    covariance,
    decay_linear,
    delay,
    delta,
    indneutralize,
    log,
    log_product,
    maximum,
    minimum,
    power,
    product,
    rank,
    scale,
    sign,
    sma,
    ts_argmax,
    ts_argmin,
    ts_corr,
    ts_max,
    ts_mean,
    ts_min,
    ts_rank,
    ts_stddev,
    ts_sum,
)


@dataclass
class Ctx:
    close: pd.Series
    open: pd.Series
    high: pd.Series
    low: pd.Series
    volume: pd.Series
    returns: pd.Series
    vwap: pd.Series

    def adv(self, d: float) -> pd.Series:
        """Average daily dollar volume over ``d`` days."""
        return ts_mean(self.close * self.volume, d)


def _ctx(df: pd.DataFrame) -> Ctx:
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    open_ = df["open"].astype(float)
    volume = df["volume"].astype(float)
    returns = close.pct_change()
    vwap = df["vwap"].astype(float) if "vwap" in df.columns else (high + low + close) / 3.0
    return Ctx(close=close, open=open_, high=high, low=low, volume=volume, returns=returns, vwap=vwap)


def _where(c: Ctx, cond: pd.Series | np.ndarray, a, b) -> pd.Series:
    return pd.Series(np.where(cond, a, b), index=c.close.index)


def a001(c: Ctx) -> pd.Series:
    return rank(ts_argmax(power(_where(c, c.returns < 0, ts_stddev(c.returns, 20), c.close), 2), 5)) - 0.5


def a002(c: Ctx) -> pd.Series:
    return -1 * correlation(rank(delta(log(c.volume), 2)), rank((c.close - c.open) / c.open), 6)


def a003(c: Ctx) -> pd.Series:
    return -1 * correlation(rank(c.open), rank(c.volume), 10)


def a004(c: Ctx) -> pd.Series:
    return -1 * ts_rank(rank(c.low), 9)


def a005(c: Ctx) -> pd.Series:
    return rank((c.open - (ts_sum(c.vwap, 10) / 10))) * (-1 * abs_(rank((c.close - c.vwap))))


def a006(c: Ctx) -> pd.Series:
    return -1 * correlation(c.open, c.volume, 10)


def a007(c: Ctx) -> pd.Series:
    return _where(
        c,
        c.adv(20) < c.volume,
        (-1 * ts_rank(abs_(delta(c.close, 7)), 60)) * sign(delta(c.close, 7)),
        -1,
    )


def a008(c: Ctx) -> pd.Series:
    base = ts_sum(c.open, 5) * ts_sum(c.returns, 5)
    return -1 * rank(base - delay(base, 10))


def a009(c: Ctx) -> pd.Series:
    d = delta(c.close, 1)
    return _where(
        c,
        0 < ts_min(d, 5),
        d,
        _where(c, ts_max(d, 5) < 0, d, -1 * d),
    )


def a010(c: Ctx) -> pd.Series:
    d = delta(c.close, 1)
    return rank(_where(c, 0 < ts_min(d, 4), d, _where(c, ts_max(d, 4) < 0, d, -1 * d)))


def a011(c: Ctx) -> pd.Series:
    return (rank(ts_max((c.vwap - c.close), 3)) + rank(ts_min((c.vwap - c.close), 3))) * rank(delta(c.volume, 3))


def a012(c: Ctx) -> pd.Series:
    return sign(delta(c.volume, 1)) * (-1 * delta(c.close, 1))


def a013(c: Ctx) -> pd.Series:
    return -1 * rank(covariance(rank(c.close), rank(c.volume), 5))


def a014(c: Ctx) -> pd.Series:
    return (-1 * rank(delta(c.returns, 3))) * correlation(c.open, c.volume, 10)


def a015(c: Ctx) -> pd.Series:
    return -1 * ts_sum(rank(correlation(rank(c.high), rank(c.volume), 3)), 3)


def a016(c: Ctx) -> pd.Series:
    return -1 * rank(covariance(rank(c.high), rank(c.volume), 5))


def a017(c: Ctx) -> pd.Series:
    return (
        (-1 * rank(ts_rank(c.close, 10)))
        * rank(delta(delta(c.close, 1), 1))
        * rank(ts_rank((c.volume / c.adv(20)), 5))
    )


def a018(c: Ctx) -> pd.Series:
    return -1 * rank((ts_stddev(abs_((c.close - c.open)), 5) + (c.close - c.open)) + correlation(c.close, c.open, 10))


def a019(c: Ctx) -> pd.Series:
    return (-1 * sign((c.close - delay(c.close, 7)) + delta(c.close, 7))) * (1 + rank((1 + ts_sum(c.returns, 250))))


def a020(c: Ctx) -> pd.Series:
    return ((-1 * rank((c.open - delay(c.high, 1)))) * rank((c.open - delay(c.close, 1)))) * rank((c.open - delay(c.low, 1)))


def a021(c: Ctx) -> pd.Series:
    close8 = ts_sum(c.close, 8) / 8
    close2 = ts_sum(c.close, 2) / 2
    std8 = ts_stddev(c.close, 8)
    return _where(
        c,
        (close8 + std8) < close2,
        -1,
        _where(
            c,
            close2 < (close8 - std8),
            1,
            _where(c, (c.volume / c.adv(20)) >= 1, 1, -1),
        ),
    )


def a022(c: Ctx) -> pd.Series:
    return -1 * (delta(correlation(c.high, c.volume, 5), 5) * rank(ts_stddev(c.close, 20)))


def a023(c: Ctx) -> pd.Series:
    return _where(c, (ts_sum(c.high, 20) / 20) < c.high, -1 * delta(c.high, 2), 0)


def a024(c: Ctx) -> pd.Series:
    ma100 = ts_sum(c.close, 100) / 100
    ratio = delta(ma100, 100) / delay(c.close, 100)
    return _where(c, ratio <= 0.05, -1 * (c.close - ts_min(c.close, 100)), -1 * delta(c.close, 3))


def a025(c: Ctx) -> pd.Series:
    return rank((((-1 * c.returns) * c.adv(20)) * c.vwap) * (c.high - c.close))


def a026(c: Ctx) -> pd.Series:
    return -1 * ts_max(correlation(ts_rank(c.volume, 5), ts_rank(c.high, 5), 5), 3)


def a027(c: Ctx) -> pd.Series:
    return _where(c, 0.5 < rank((ts_sum(correlation(rank(c.volume), rank(c.vwap), 6), 2) / 2.0)), -1, 1)


def a028(c: Ctx) -> pd.Series:
    return scale(((correlation(c.adv(20), c.low, 5) + (c.high + c.low) / 2) - c.close))


def a029(c: Ctx) -> pd.Series:
    d = -1 * rank(delta((c.close - 1), 5))
    inner = ts_min(rank(rank(d)), 2)
    loged = log(ts_sum(inner, 1))
    ranked = rank(rank(scale(loged)))
    return minimum(product(ranked, 1), 5) + ts_rank(delay((-1 * c.returns), 6), 5)


def a030(c: Ctx) -> pd.Series:
    s = sign(c.close - delay(c.close, 1)) + sign(delay(c.close, 1) - delay(c.close, 2)) + sign(delay(c.close, 2) - delay(c.close, 3))
    return ((1.0 - rank(s)) * ts_sum(c.volume, 5)) / ts_sum(c.volume, 20)


def a031(c: Ctx) -> pd.Series:
    return (
        rank(rank(rank(decay_linear((-1 * rank(rank(delta(c.close, 10)))), 10))))
        + rank((-1 * delta(c.close, 3)))
        + sign(scale(correlation(c.adv(20), c.low, 12)))
    )


def a032(c: Ctx) -> pd.Series:
    return scale(((ts_sum(c.close, 7) / 7) - c.close)) + (20 * scale(correlation(c.vwap, delay(c.close, 5), 230)))


def a033(c: Ctx) -> pd.Series:
    return rank(-1 * (1 - c.open / c.close))


def a034(c: Ctx) -> pd.Series:
    return rank(((1 - rank(ts_stddev(c.returns, 2) / ts_stddev(c.returns, 5))) + (1 - rank(delta(c.close, 1)))))


def a035(c: Ctx) -> pd.Series:
    return (ts_rank(c.volume, 32) * (1 - ts_rank((c.close + c.high) - c.low, 16))) * (1 - ts_rank(c.returns, 32))


def a036(c: Ctx) -> pd.Series:
    return (
        (2.21 * rank(correlation((c.close - c.open), delay(c.volume, 1), 15)))
        + (0.7 * rank((c.open - c.close)))
        + (0.73 * rank(ts_rank(delay((-1 * c.returns), 6), 5)))
        + rank(abs_(correlation(c.vwap, c.adv(20), 6)))
        + (0.6 * rank(((ts_sum(c.close, 200) / 200 - c.open) * (c.close - c.open))))
    )


def a037(c: Ctx) -> pd.Series:
    return rank(correlation(delay((c.open - c.close), 1), c.close, 200)) + rank((c.open - c.close))


def a038(c: Ctx) -> pd.Series:
    return (-1 * rank(ts_rank(c.close, 10))) * rank((c.close / c.open))


def a039(c: Ctx) -> pd.Series:
    return (-1 * rank(delta(c.close, 7) * (1 - rank(decay_linear((c.volume / c.adv(20)), 9))))) * (1 + rank(ts_sum(c.returns, 250)))


def a040(c: Ctx) -> pd.Series:
    return (-1 * rank(ts_stddev(c.high, 10))) * correlation(c.high, c.volume, 10)


def a041(c: Ctx) -> pd.Series:
    return power((c.high * c.low), 0.5) - c.vwap


def a042(c: Ctx) -> pd.Series:
    return rank(c.vwap - c.close) / rank(c.vwap + c.close)


def a043(c: Ctx) -> pd.Series:
    return ts_rank(c.volume / c.adv(20), 20) * ts_rank(-1 * delta(c.close, 7), 8)


def a044(c: Ctx) -> pd.Series:
    return -1 * correlation(c.high, rank(c.volume), 5)


def a045(c: Ctx) -> pd.Series:
    return (-1 * ((rank(ts_sum(delay(c.close, 5), 20) / 20) * correlation(c.close, c.volume, 2)) * rank(correlation(ts_sum(c.close, 5), ts_sum(c.close, 20), 2))))


def a046(c: Ctx) -> pd.Series:
    val = ((delay(c.close, 20) - delay(c.close, 10)) / 10) - ((delay(c.close, 10) - c.close) / 10)
    return _where(c, 0.25 < val, -1, _where(c, val < 0, 1, (-1 * (c.close - delay(c.close, 1)))))


def a047(c: Ctx) -> pd.Series:
    return ((((rank(1 / c.close) * c.volume) / c.adv(20)) * ((c.high * rank(c.high - c.close)) / (ts_sum(c.high, 5) / 5))) - rank((c.vwap - delay(c.vwap, 5))))


def a048(c: Ctx) -> pd.Series:
    num = indneutralize((correlation(delta(c.close, 1), delta(delay(c.close, 1), 1), 250) * delta(c.close, 1)) / c.close)
    denom = ts_sum(power(delta(c.close, 1) / delay(c.close, 1), 2), 250)
    return num / denom


def a049(c: Ctx) -> pd.Series:
    val = ((delay(c.close, 20) - delay(c.close, 10)) / 10) - ((delay(c.close, 10) - c.close) / 10)
    return _where(c, val < -0.1, 1, (-1 * (c.close - delay(c.close, 1))))


def a050(c: Ctx) -> pd.Series:
    return -1 * ts_max(rank(correlation(rank(c.volume), rank(c.vwap), 5)), 5)


def a051(c: Ctx) -> pd.Series:
    val = ((delay(c.close, 20) - delay(c.close, 10)) / 10) - ((delay(c.close, 10) - c.close) / 10)
    return _where(c, val < -0.05, 1, (-1 * (c.close - delay(c.close, 1))))


def a052(c: Ctx) -> pd.Series:
    return ((-1 * ts_min(c.low, 5)) + delay(ts_min(c.low, 5), 5)) * rank(((ts_sum(c.returns, 240) - ts_sum(c.returns, 20)) / 220)) * ts_rank(c.volume, 5)


def a053(c: Ctx) -> pd.Series:
    return -1 * delta((((c.close - c.low) - (c.high - c.close)) / (c.close - c.low)), 9)


def a054(c: Ctx) -> pd.Series:
    return (-1 * ((c.low - c.close) * power(c.open, 5))) / ((c.low - c.high) * power(c.close, 5))


def a055(c: Ctx) -> pd.Series:
    rng = ts_max(c.high, 12) - ts_min(c.low, 12)
    return -1 * correlation(rank((c.close - ts_min(c.low, 12)) / rng), rank(c.volume), 6)


def a056(c: Ctx) -> pd.Series:
    cap = c.adv(20)  # market cap substitute (documented)
    return 0 - (1 * (rank((ts_sum(c.returns, 10) / ts_sum(ts_sum(c.returns, 2), 3))) * rank((c.returns * cap))))


def a057(c: Ctx) -> pd.Series:
    return 0 - (1 * ((c.close - c.vwap) / decay_linear(rank(ts_argmax(c.close, 30)), 2)))


def a058(c: Ctx) -> pd.Series:
    return -1 * ts_rank(decay_linear(correlation(indneutralize(c.vwap), c.volume, 4), 8), 6)


def a059(c: Ctx) -> pd.Series:
    return -1 * ts_rank(decay_linear(correlation(indneutralize(c.vwap), c.volume, 4), 16), 8)


def a060(c: Ctx) -> pd.Series:
    return 0 - (1 * ((2 * scale(rank((((c.close - c.low) - (c.high - c.close)) / (c.high - c.low)) * c.volume))) - scale(rank(ts_argmax(c.close, 10)))))


def a061(c: Ctx) -> pd.Series:
    return rank(c.vwap - ts_min(c.vwap, 16)) < rank(correlation(c.vwap, c.adv(180), 18))


def a062(c: Ctx) -> pd.Series:
    return -1 * (rank(correlation(c.vwap, ts_sum(c.adv(20), 22), 10)) < rank(((rank(c.open) + rank(c.open)) < (rank((c.high + c.low) / 2) + rank(c.high)))))


def a063(c: Ctx) -> pd.Series:
    blended = c.vwap * 0.318108 + c.open * (1 - 0.318108)
    return (rank(decay_linear(delta(indneutralize(c.close), 2), 8)) - rank(decay_linear(correlation(blended, ts_sum(c.adv(180), 37), 14), 12))) * -1


def a064(c: Ctx) -> pd.Series:
    blended = (c.high + c.low) / 2 * 0.178404 + c.vwap * (1 - 0.178404)
    return -1 * (rank(correlation(ts_sum((c.open * 0.178404 + c.low * (1 - 0.178404)), 13), ts_sum(c.adv(120), 13), 17)) < rank(delta(blended, 4)))


def a065(c: Ctx) -> pd.Series:
    blended = c.open * 0.00817205 + c.vwap * (1 - 0.00817205)
    return -1 * (rank(correlation(blended, ts_sum(c.adv(60), 9), 6)) < rank(c.open - ts_min(c.open, 14)))


def a066(c: Ctx) -> pd.Series:
    low_blend = c.low * 0.96633 + c.low * (1 - 0.96633)
    return (rank(decay_linear(delta(c.vwap, 4), 7)) + ts_rank(decay_linear(((low_blend - c.vwap) / (c.open - (c.high + c.low) / 2)), 11), 7)) * -1


def a067(c: Ctx) -> pd.Series:
    return power(rank(c.high - ts_min(c.high, 2)), rank(correlation(rank(c.vwap), rank(c.volume), 6)))


def a068(c: Ctx) -> pd.Series:
    blended = c.close * 0.518371 + c.low * (1 - 0.518371)
    return (ts_rank(correlation(rank(c.high), rank(c.adv(15)), 9), 14) < rank(delta(blended, 1))) * -1


def a069(c: Ctx) -> pd.Series:
    blended = c.close * 0.490655 + c.vwap * (1 - 0.490655)
    return (power(rank(ts_max(delta(indneutralize(c.vwap), 3), 5)), ts_rank(correlation(blended, c.adv(20), 5), 9))) * -1


def a070(c: Ctx) -> pd.Series:
    return (power(rank(delta(c.vwap, 1)), ts_rank(correlation(indneutralize(c.close), c.adv(50), 18), 18))) * -1


def a071(c: Ctx) -> pd.Series:
    return maximum(
        ts_rank(decay_linear(correlation(ts_rank(c.close, 3), ts_rank(c.adv(180), 12), 18), 4), 16),
        ts_rank(decay_linear(power(rank((c.low + c.open) - (c.vwap + c.vwap)), 2), 16), 4),
    )


def a072(c: Ctx) -> pd.Series:
    return rank(decay_linear(correlation((c.high + c.low) / 2, c.adv(40), 9), 10)) / rank(decay_linear(correlation(ts_rank(c.vwap, 4), ts_rank(c.volume, 19), 7), 3))


def a073(c: Ctx) -> pd.Series:
    blended = c.open * 0.147155 + c.low * (1 - 0.147155)
    return maximum(
        rank(decay_linear(delta(c.vwap, 5), 3)),
        ts_rank(decay_linear(-1 * delta(blended, 2) / blended, 3), 17),
    ) * -1


def a074(c: Ctx) -> pd.Series:
    blended = c.high * 0.0261661 + c.vwap * (1 - 0.0261661)
    return -1 * (rank(correlation(c.close, ts_sum(c.adv(30), 37), 15)) < rank(correlation(rank(blended), rank(c.volume), 11)))


def a075(c: Ctx) -> pd.Series:
    return rank(correlation(c.vwap, c.volume, 4)) < rank(correlation(rank(c.low), rank(c.adv(50)), 12))


def a076(c: Ctx) -> pd.Series:
    return maximum(
        rank(decay_linear(delta(c.vwap, 1), 12)),
        ts_rank(decay_linear(ts_rank(correlation(indneutralize(c.low), c.adv(81), 8), 20), 17), 19),
    ) * -1


def a077(c: Ctx) -> pd.Series:
    return minimum(
        rank(decay_linear((((c.high + c.low) / 2 + c.high) - (c.vwap + c.high)), 20)),
        rank(decay_linear(correlation((c.high + c.low) / 2, c.adv(40), 3), 6)),
    )


def a078(c: Ctx) -> pd.Series:
    blended = c.low * 0.352233 + c.vwap * (1 - 0.352233)
    return power(rank(correlation(ts_sum(blended, 20), ts_sum(c.adv(40), 20), 7)), rank(correlation(rank(c.vwap), rank(c.volume), 6)))


def a079(c: Ctx) -> pd.Series:
    blended = c.close * 0.60733 + c.open * (1 - 0.60733)
    return rank(delta(indneutralize(blended), 1)) < rank(correlation(ts_rank(c.vwap, 4), ts_rank(c.adv(150), 9), 15))


def a080(c: Ctx) -> pd.Series:
    blended = c.open * 0.868128 + c.high * (1 - 0.868128)
    return (power(rank(sign(delta(indneutralize(blended), 4))), ts_rank(correlation(c.high, c.adv(10), 5), 6))) * -1


def a081(c: Ctx) -> pd.Series:
    return (rank(log_product(c.adv(30), 10)) < rank(log_product(c.close, 3))) * -1


def a082(c: Ctx) -> pd.Series:
    return rank(correlation(log(rank(c.close / c.vwap)), rank(c.volume), 12)) < rank(correlation(rank(c.close), rank(c.adv(60)), 13))


def a083(c: Ctx) -> pd.Series:
    return -1 * rank(covariance(rank(c.high), rank(c.adv(15)), 9))


def a084(c: Ctx) -> pd.Series:
    return sign(correlation(rank(c.vwap - ts_min(c.vwap, 12)), rank(correlation(ts_rank(c.vwap, 20), ts_rank(c.adv(60), 4), 18)), 12))


def a085(c: Ctx) -> pd.Series:
    blended = c.high * 0.876703 + c.close * (1 - 0.876703)
    return power(rank(correlation(blended, c.adv(30), 10)), rank(correlation(ts_rank((c.high + c.low) / 2, 4), ts_rank(c.volume, 10), 7)))


def a086(c: Ctx) -> pd.Series:
    return (ts_rank(correlation(c.close, ts_sum(c.adv(20), 15), 6), 20) < rank((c.open + c.close) - (c.vwap + c.open))) * -1


def a087(c: Ctx) -> pd.Series:
    blended = c.close * 0.369701 + c.vwap * (1 - 0.369701)
    return maximum(
        rank(decay_linear(delta(blended, 2), 3)),
        ts_rank(decay_linear(abs_(correlation(indneutralize(c.adv(81)), c.close, 13)), 5), 14),
    ) * -1


def a088(c: Ctx) -> pd.Series:
    return minimum(
        rank(decay_linear(((rank(c.open) + rank(c.low)) - (rank(c.high) + rank(c.close))), 8)),
        ts_rank(decay_linear(correlation(ts_rank(c.close, 8), ts_rank(c.adv(60), 21), 8), 7), 3),
    )


def a089(c: Ctx) -> pd.Series:
    return ts_rank(decay_linear(correlation(c.low, c.adv(10), 7), 6), 4) - ts_rank(decay_linear(delta(indneutralize(c.vwap), 3), 10), 15)


def a090(c: Ctx) -> pd.Series:
    return (power(rank(c.close - ts_max(c.close, 5)), ts_rank(correlation(indneutralize(c.adv(40)), c.low, 5), 3))) * -1


def a091(c: Ctx) -> pd.Series:
    return (ts_rank(decay_linear(decay_linear(correlation(indneutralize(c.close), c.volume, 10), 16), 4), 5) - rank(decay_linear(delta(c.vwap, 3), 6))) * -1


def a092(c: Ctx) -> pd.Series:
    return minimum(
        ts_rank(decay_linear((((c.high + c.low) / 2 + c.close) < (c.low + c.open)), 15), 19),
        ts_rank(decay_linear(correlation(rank(c.low), rank(c.adv(30)), 8), 7), 7),
    )


def a093(c: Ctx) -> pd.Series:
    blended = c.close * 0.524434 + c.vwap * (1 - 0.524434)
    return ts_rank(decay_linear(correlation(indneutralize(c.vwap), c.adv(81), 17), 20), 8) / rank(decay_linear(delta(blended, 3), 16))


def a094(c: Ctx) -> pd.Series:
    return (power(rank(c.vwap - ts_min(c.vwap, 12)), ts_rank(correlation(ts_rank(c.vwap, 20), ts_rank(c.adv(60), 4), 18), 12))) * -1


def a095(c: Ctx) -> pd.Series:
    return rank(c.open - ts_min(c.open, 12)) < ts_rank(power(rank(correlation(ts_sum((c.high + c.low) / 2, 19), ts_sum(c.adv(40), 19), 13)), 5), 12)


def a096(c: Ctx) -> pd.Series:
    return maximum(
        ts_rank(decay_linear(correlation(rank(c.vwap), rank(c.volume), 4), 4), 8),
        ts_rank(decay_linear(ts_argmax(correlation(ts_rank(c.close, 7), ts_rank(c.adv(60), 4), 4), 13), 14), 13),
    ) * -1


def a097(c: Ctx) -> pd.Series:
    blended = c.low * 0.721001 + c.vwap * (1 - 0.721001)
    return (rank(decay_linear(delta(indneutralize(blended), 3), 20)) - ts_rank(decay_linear(ts_rank(correlation(ts_rank(c.low, 8), ts_rank(c.adv(60), 17), 5), 19), 16), 7)) * -1


def a098(c: Ctx) -> pd.Series:
    return rank(decay_linear(correlation(c.vwap, ts_sum(c.adv(5), 26), 5), 7)) - rank(decay_linear(ts_rank(ts_argmin(correlation(rank(c.open), rank(c.adv(15)), 21), 9), 7), 8))


def a099(c: Ctx) -> pd.Series:
    return -1 * (rank(correlation(ts_sum((c.high + c.low) / 2, 20), ts_sum(c.adv(60), 20), 9)) < rank(correlation(c.low, c.volume, 6)))


def a100(c: Ctx) -> pd.Series:
    spread = ((c.close - c.low) - (c.high - c.close)) / (c.high - c.low) * c.volume
    return 0 - (1 * (((1.5 * scale(indneutralize(indneutralize(rank(spread))))) - scale(indneutralize((correlation(c.close, rank(c.adv(20)), 5) - rank(ts_argmin(c.close, 30)))))) * (c.volume / c.adv(20))))


def a101(c: Ctx) -> pd.Series:
    return (c.close - c.open) / ((c.high - c.low) + 0.001)


ALPHAS: dict[str, object] = {
    f"alpha101_{i:03d}": fn for i, fn in enumerate(
        (a001, a002, a003, a004, a005, a006, a007, a008, a009, a010,
         a011, a012, a013, a014, a015, a016, a017, a018, a019, a020,
         a021, a022, a023, a024, a025, a026, a027, a028, a029, a030,
         a031, a032, a033, a034, a035, a036, a037, a038, a039, a040,
         a041, a042, a043, a044, a045, a046, a047, a048, a049, a050,
         a051, a052, a053, a054, a055, a056, a057, a058, a059, a060,
         a061, a062, a063, a064, a065, a066, a067, a068, a069, a070,
         a071, a072, a073, a074, a075, a076, a077, a078, a079, a080,
         a081, a082, a083, a084, a085, a086, a087, a088, a089, a090,
         a091, a092, a093, a094, a095, a096, a097, a098, a099, a100,
         a101),
        start=1,
    )
}

ALPHA_DESCRIPTIONS: dict[str, str] = {
    "alpha101_001": "Rank of Ts_ArgMax of signed-power stddev/close; contrarian timing.",
    "alpha101_002": "Negative 6-day correlation of volume and open-to-close spread ranks.",
    "alpha101_003": "Negative 10-day correlation of open vs volume ranks.",
    "alpha101_004": "Negative 9-day Ts_Rank of the rank of the low.",
    "alpha101_005": "Rank of open vs 10-day VWAP mean, weighted by rank of close-VWAP gap.",
    "alpha101_006": "Negative 10-day correlation of open and volume.",
    "alpha101_007": "Volume above ADV20 → momentum-of-7-day-move scaled by Ts_Rank; else flat.",
    "alpha101_008": "Contrarian 10-day momentum of (open x returns) product.",
    "alpha101_009": "Short-term mean-reversion in 1-day close moves.",
    "alpha101_010": "Ranks the 4-day version of alpha009.",
    "alpha101_011": "VWAP distance from close over 3 days combined with volume change.",
    "alpha101_012": "Sign of volume change times negative 1-day close move.",
    "alpha101_013": "Negative rank of 5-day covariance of close/volume ranks.",
    "alpha101_014": "Negative momentum of 3-day returns x open-volume correlation.",
    "alpha101_015": "Negative 3-day sum of 3-day high/volume correlation ranks.",
    "alpha101_016": "Negative rank of 5-day covariance of high/volume ranks.",
    "alpha101_017": "Close Ts_Rank, acceleration, and volume ADV ratio ranks combined.",
    "alpha101_018": "Negative rank of intraday range + 5-day std + close-open correlation.",
    "alpha101_019": "Sign of 7-day price change times 250-day return memory.",
    "alpha101_020": "Open vs previous high/close/low gaps, ranked and signed.",
    "alpha101_021": "Regime switch between 2-day and 8-day means around the 8-day std band.",
    "alpha101_022": "Negative change in high-volume correlation scaled by close vol rank.",
    "alpha101_023": "High above 20-day mean → negative 2-day high change, else flat.",
    "alpha101_024": "Slow 100-day momentum regime → distance from 100-day low; else 3-day move.",
    "alpha101_025": "Rank of return x ADV x VWAP x (high-close).",
    "alpha101_026": "Negative 3-day max of 5-day volume/high Ts_Rank correlation.",
    "alpha101_027": "Volume-VWAP rank correlation regime switch.",
    "alpha101_028": "Scale of ADV-low correlation plus mid-price minus close.",
    "alpha101_029": "High-frequency 5-day min of ranked momentum plus 6-day lagged return Ts_Rank.",
    "alpha101_030": "3-day price direction memory x 5-day volume over 20-day volume.",
    "alpha101_031": "Deep-ranked 10-day decay of close momentum + 3-day move + ADV-low corr sign.",
    "alpha101_032": "7-day mean reversion scaled + 20x scaled 230-day VWAP-lag correlation.",
    "alpha101_033": "Rank of (1 - open/close) reversal.",
    "alpha101_034": "Rank of low 2-day vol regime plus 1-day momentum reversal.",
    "alpha101_035": "Volume and range Ts_Ranks combined with return Ts_Rank.",
    "alpha101_036": "Multi-component momentum/volume/VWAP blend.",
    "alpha101_037": "Open-close spread lag correlated over 200 days plus spread rank.",
    "alpha101_038": "Negative close Ts_Rank times open-to-close ratio rank.",
    "alpha101_039": "7-day momentum x volume-decay memory x 250-day return memory.",
    "alpha101_040": "Negative 10-day high vol rank times high-volume correlation.",
    "alpha101_041": "Square-root of high x low minus VWAP (volatility proxy).",
    "alpha101_042": "VWAP-close spread rank relative to VWAP+close rank.",
    "alpha101_043": "20-day volume ADV Ts_Rank x negative 7-day move Ts_Rank.",
    "alpha101_044": "Negative 5-day correlation of high and volume rank.",
    "alpha101_045": "Slow 20-day close mean rank x short correlations of close/volume sums.",
    "alpha101_046": "10-day momentum regime between 0.25 and 0.",
    "alpha101_047": "Volume/ADV-weighted high-close gap minus VWAP drift rank.",
    "alpha101_048": "250-day autocorrelation of 1-day moves scaled by realized variance.",
    "alpha101_049": "Momentum regime below -0.1.",
    "alpha101_050": "Negative 5-day max of volume-VWAP correlation rank.",
    "alpha101_051": "Momentum regime below -0.05.",
    "alpha101_052": "5-day low change x 240-day return differential x volume Ts_Rank.",
    "alpha101_053": "Negative 9-day change of intraday-range position.",
    "alpha101_054": "Extreme price-level leverage ratio.",
    "alpha101_055": "Range-normalized position correlated with volume rank over 6 days.",
    "alpha101_056": "Ranked 10-day returns over 2-day blocks x returns x cap proxy.",
    "alpha101_057": "VWAP deviation over decayed rank of 30-day argmax.",
    "alpha101_058": "Ts_Rank of decayed correlation of neutralized VWAP and volume.",
    "alpha101_059": "Ts_Rank of decayed correlation of blended VWAP and volume.",
    "alpha101_060": "Double-scaled intraday range x volume minus 10-day argmax rank.",
    "alpha101_061": "VWAP deviation from 16-day low vs long VWAP-ADV correlation.",
    "alpha101_062": "Rank comparison: VWAP-ADV correlation vs open/mid/high ranks.",
    "alpha101_063": "Decayed neutralized close change vs blended price-ADV correlation.",
    "alpha101_064": "Rank comparison of blended price-ADV correlation vs blended move.",
    "alpha101_065": "Rank comparison of blended open/VWAP correlation vs open low-distance.",
    "alpha101_066": "Decayed VWAP change + VWAP deviation regime.",
    "alpha101_067": "High momentum rank powered by volume-VWAP correlation rank.",
    "alpha101_068": "Rank comparison of high-ADV correlation Ts_Rank vs blended close move.",
    "alpha101_069": "Neutralized VWAP range rank vs blended close-ADV correlation.",
    "alpha101_070": "VWAP change rank vs neutralized close-ADV correlation.",
    "alpha101_071": "Max of two decayed Ts_Rank momentum signals.",
    "alpha101_072": "Ratio of mid-ADV correlation decay to VWAP-volume correlation decay.",
    "alpha101_073": "Max of VWAP change and blended low-price change Ts_Rank.",
    "alpha101_074": "Rank comparison: close vs ADV correlation vs blended high-volume correlation.",
    "alpha101_075": "VWAP-volume correlation rank vs low-ADV correlation rank.",
    "alpha101_076": "Max of VWAP change and neutralized low-ADV correlation decay.",
    "alpha101_077": "Min of two mean-reversion decayed ranks.",
    "alpha101_078": "Blended price/ADV correlation rank powered by VWAP-volume correlation rank.",
    "alpha101_079": "Neutralized blended close change vs VWAP-ADV correlation Ts_Rank.",
    "alpha101_080": "Neutralized blended open/high sign change vs high-ADV correlation.",
    "alpha101_081": "Log-product of ADV vs log-product of close (regime flip).",
    "alpha101_082": "Rank comparison of VWAP-close log rank correlation vs close-ADV correlation.",
    "alpha101_083": "Negative rank of covariance of high and ADV ranks.",
    "alpha101_084": "Sign of VWAP-low distance correlation vs VWAP-ADV Ts_Rank correlation.",
    "alpha101_085": "Blended high/close vs ADV correlation, powered by range-volume correlation.",
    "alpha101_086": "Close-ADV correlation Ts_Rank vs open/close-VWAP regime.",
    "alpha101_087": "Max of blended close change and neutralized ADV-close correlation decay.",
    "alpha101_088": "Min of open/low/high/close rank decay and close-ADV correlation decay.",
    "alpha101_089": "Low-ADV correlation decay Ts_Rank minus neutralized VWAP change.",
    "alpha101_090": "Close distance from 5-day high powered by neutralized ADV-low correlation.",
    "alpha101_091": "Double-decayed neutralized close-volume correlation minus VWAP change.",
    "alpha101_092": "Min of two regime Ts_Ranks (price/volume patterns).",
    "alpha101_093": "Neutralized VWAP-ADV correlation decay over blended close change.",
    "alpha101_094": "VWAP low-distance rank powered by VWAP-ADV Ts_Rank correlation.",
    "alpha101_095": "Open low-distance rank vs 5th-power ADV correlation Ts_Rank.",
    "alpha101_096": "Max of VWAP-volume and close-ADV Ts_Rank decay signals.",
    "alpha101_097": "Neutralized blended low-price change minus low-ADV correlation decay.",
    "alpha101_098": "VWAP-ADV correlation decay vs open-ADV argmin Ts_Rank decay.",
    "alpha101_099": "Rank comparison of mid-price/ADV correlation vs low-volume correlation.",
    "alpha101_100": "Volume/ADV-scaled intraday range signal with double neutralization.",
    "alpha101_101": "Intraday close-open spread normalized by range (plus epsilon).",
}


def compute(df: pd.DataFrame, names: list[str] | None = None) -> dict[str, pd.Series]:
    """Compute the requested (default: all) alphas over an OHLCV frame.

    Outputs are sanitized so ``inf`` becomes NaN (constant windows and log/0
    poles are undefined, never a number). Warm-up bars are NaN.
    """
    c = _ctx(df)
    wanted = names or list(ALPHAS)
    out: dict[str, pd.Series] = {}
    for name in wanted:
        fn = ALPHAS.get(name)
        if fn is None:
            raise KeyError(f"unknown alpha '{name}'")
        s = pd.Series(fn(c), index=df.index, name=name)
        out[name] = s.replace([np.inf, -np.inf], np.nan)
    return out
