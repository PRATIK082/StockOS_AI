"""Tests for the quantlib package (risk / portfolio / cashflow / options)."""

from __future__ import annotations

import numpy as np
import pytest


def _returns(n: int = 500, seed: int = 7, mu: float = 0.0003, sigma: float = 0.015) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(mu, sigma, n)


def test_parametric_and_cornish_fisher_var() -> None:
    from app.services.quantlib.risk import cornish_fisher_var, parametric_var

    r = _returns()
    p = parametric_var(r, level=0.05)
    assert p["var"] > 0 and p["es"] >= p["var"]
    cf = cornish_fisher_var(r, level=0.05)
    assert cf["var"] > 0 and abs(cf["skewness"]) < 0.5
    assert parametric_var([1, 2, 3], level=0.05)["error"]


def test_evt_var() -> None:
    from app.services.quantlib.risk import evt_var

    r = _returns()
    e = evt_var(r, level=0.06, threshold_pct=0.95)
    assert e["n_exceedances"] >= 10
    assert e["var"] > 0 and e["es"] >= e["var"]
    assert evt_var(r, level=0.08, threshold_pct=0.95)["var"] > e["var"]


def test_ewma_vol() -> None:
    from app.services.quantlib.risk import ewma_vol

    v = ewma_vol(_returns())
    assert 0.005 < v["ewma_vol"] < 0.05
    assert ewma_vol(_returns(), lambda_=2.0)["error"]


def test_black_litterman() -> None:
    from app.services.quantlib.portfolio import black_litterman

    assets = ["A", "B", "C"]
    cov = np.array([[0.04, 0.01, 0.005], [0.01, 0.03, 0.006], [0.005, 0.006, 0.02]])
    mu = {"A": 0.12, "B": 0.09, "C": 0.06}
    w = {"A": 0.4, "B": 0.35, "C": 0.25}
    views = [{"assets": ["A", "C"], "weights": [1.0, -1.0], "return": 0.08}]
    out = black_litterman(mu, cov, w, views, risk_free=0.03)
    assert out["n_views"] == 1
    assert set(out["posterior_returns"]) == set(assets)
    assert abs(sum(out["optimal_weights"].values()) - 1) < 1e-6
    assert out["posterior_covariance"][0][0] > 0


def test_black_litterman_no_views() -> None:
    from app.services.quantlib.portfolio import black_litterman

    cov = np.eye(2)
    out = black_litterman({"A": 0.1, "B": 0.08}, cov, {"A": 0.5, "B": 0.5}, [])
    assert out["error"]


def test_brinson_attribution() -> None:
    from app.services.quantlib.portfolio import brinson_attribution

    rp = {"A": 0.08, "B": 0.04, "C": 0.10}
    rb = {"A": 0.06, "B": 0.05, "C": 0.09}
    wp = {"A": 0.5, "B": 0.3, "C": 0.2}
    wb = {"A": 0.4, "B": 0.4, "C": 0.2}
    out = brinson_attribution(rp, rb, wp, wb)
    t = out["totals"]
    expected_active = 0.5 * 0.08 + 0.3 * 0.04 + 0.2 * 0.10 - (0.4 * 0.06 + 0.4 * 0.05 + 0.2 * 0.09)
    assert t["active_return"] == pytest.approx(expected_active, abs=1e-6)
    assert t["active_return"] == pytest.approx(t["allocation"] + t["selection"] + t["interaction"], abs=1e-6)


def test_cashflow_npv_irr_xirr() -> None:
    from app.services.quantlib.cashflow import irr, npv, xirr

    amounts = [-100, 30, 30, 30, 30]
    assert npv(0.0, amounts) == pytest.approx(20.0)
    r = irr(amounts)
    assert abs(npv(r, amounts)) < 1e-6
    assert 0.05 < r < 0.10
    dates = ["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"]
    x = xirr(amounts, dates)
    assert abs(npv(x, amounts)) < 1e-6 or -1 < x < 5
    with pytest.raises(ValueError):
        irr([100, 100, 100])


def test_implied_vol_and_greeks() -> None:
    from app.services.quantlib.options import greeks, implied_volatility

    g = greeks(spot=100, strike=100, time_to_expiry=0.25, volatility=0.25, option_type="call")
    assert g["price"] > 0 and 0 < g["delta"] < 1
    iv = implied_volatility(g["price"], 100, 100, 0.25, "call")
    assert iv is not None and abs(iv - 0.25) < 1e-3
    assert implied_volatility(0.05, 100, 50, 0.25, "put") is None  # below intrinsic
    assert implied_volatility(g["price"] * 0.9, 100, 100, 0.25, "call") is not None
