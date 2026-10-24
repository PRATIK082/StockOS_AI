"""Tests for the technical indicators module."""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.indicators import ema, macd, rsi, sma, sma_cross


@pytest.fixture
def closes() -> pd.Series:
    # Slowly rising series.
    return pd.Series([float(i) for i in range(1, 101)], dtype="float64")


def test_sma(closes: pd.Series) -> None:
    s = sma(closes, 5)
    assert s.iloc[4] == pytest.approx(3.0)
    assert s.iloc[:4].isna().all()


def test_ema(closes: pd.Series) -> None:
    e = ema(closes, 5)
    assert not e.isna().all()
    # EMA of an increasing series must lag below the latest value.
    assert e.iloc[-1] < closes.iloc[-1]


def test_rsi_bounds(closes: pd.Series) -> None:
    r = rsi(closes, 14)
    valid = r.dropna()
    assert ((valid >= 0) & (valid <= 100)).all()


def test_rsi_up_only_is_high(closes: pd.Series) -> None:
    r = rsi(closes, 14)
    assert r.dropna().iloc[-1] > 70


def test_macd_returns_triple(closes: pd.Series) -> None:
    m, s, h = macd(closes)
    assert len(m) == len(closes)
    assert not m.isna().all()
    # Histogram = macd - signal.
    assert h.dropna().iloc[-1] == pytest.approx((m - s).dropna().iloc[-1], abs=1e-6)


def test_sma_cross_up() -> None:
    # V-shaped series: declines then recovers, producing a fast/slow cross.
    series = pd.Series([50 + i for i in range(40, 0, -1)] + [50 + i for i in range(1, 61)])
    crosses = sma_cross(series, 5, 20)
    assert (crosses == 1).sum() >= 1
