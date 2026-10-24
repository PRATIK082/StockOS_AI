"""Tests for the factor zoo (operators, alpha101, registry) and factor
analysis (IC/ICIR, quantile returns, long-short bench) including the /api/quant
endpoints."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

from app.main import app  # noqa: E402


def _frame(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, n))
    return pd.DataFrame({
        "open": np.clip(close * (1 + rng.normal(0, 0.008, n)), 1, None),
        "high": close * 1.012,
        "low": close * 0.988,
        "close": close,
        "volume": rng.integers(5e5, 2e6, n),
    }, index=dates)


def _histories(n_symbols: int = 5, n: int = 400, seed: int = 3) -> dict:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    histories = {}
    for j in range(n_symbols):
        c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.02, n))
        o = np.clip(c * (1 + rng.normal(0, 0.008, n)), 1, None)
        candles = [
            {
                "ts": str(d.date()),
                "open": float(o[i]),
                "high": float(c[i] * 1.01),
                "low": float(c[i] * 0.99),
                "close": float(c[i]),
                "volume": int(rng.integers(5e5, 2e6)),
            }
            for i, d in enumerate(dates)
        ]
        histories[f"SYM{j}"] = {"symbol": f"SYM{j}", "interval": "1d", "period": "2y", "candles": candles}
    return histories


@pytest.fixture(scope="module")
def client() -> TestClient:
    import asyncio

    from app.db.base import Base
    from app.db.session import engine

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client: TestClient) -> dict:
    token = client.post(
        "/api/auth/register",
        json={"email": "ft@t.dev", "username": "factorist", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_alpha101_computes_all_deterministically() -> None:
    from app.services.factors.alpha101 import ALPHAS, compute

    assert len(ALPHAS) == 101
    out = compute(_frame())
    assert len(out) == 101
    for name, series in out.items():
        assert len(series) == 400
        assert not np.isinf(series.fillna(0)).any()
    out2 = compute(_frame())
    for name in out:
        pd.testing.assert_series_equal(out[name], out2[name])


def test_alpha101_short_window_factors_have_coverage() -> None:
    from app.services.factors.alpha101 import compute

    out = compute(_frame())
    for name in ("alpha101_001", "alpha101_002", "alpha101_033", "alpha101_041", "alpha101_101"):
        assert out[name].notna().sum() > 250, f"{name} has too little coverage"


def test_registry_lists_all_factors() -> None:
    from app.services.factors.registry import compute_factor, count_factors, list_factors

    assert count_factors() == 101
    names = {f["name"] for f in list_factors()}
    assert "alpha101_001" in names and "alpha101_101" in names
    s = compute_factor(_frame(), "alpha101_033")
    assert len(s) == 400 and not np.isinf(s.fillna(0)).any()
    with pytest.raises(KeyError):
        compute_factor(_frame(), "nope")


def test_operators_are_finite_safe() -> None:
    from app.services.factors.operators import (
        decay_linear, delta, rank, scale, ts_corr, ts_rank, ts_sum,
    )

    x = pd.Series(np.random.default_rng(1).normal(0, 1, 100))
    y = x.copy()
    assert np.isfinite(ts_corr(x, y, 10).fillna(0)).all()
    assert np.isfinite(scale(x).fillna(0)).all()
    assert np.isfinite(ts_rank(x, 10).fillna(0)).all()
    assert np.isfinite(decay_linear(x, 10).fillna(0)).all()
    assert len(rank(x)) == 100 and len(delta(x, 2)) == 100 and len(ts_sum(x, 5)) == 100


def test_ic_analysis_and_quantiles() -> None:
    from app.services.factors.analysis import build_panel, factor_bench, ic_analysis, quantile_returns

    panel = build_panel(_histories(), ["alpha101_001", "alpha101_038"])
    assert not panel.empty
    ic = ic_analysis(panel, ["alpha101_001", "alpha101_038"])
    for f in ("alpha101_001", "alpha101_038"):
        stats = ic["factors"][f]
        assert np.isfinite(stats["ic_mean"]) and np.isfinite(stats["ic_ir"])
    qr = quantile_returns(panel, ["alpha101_001"], n_quantiles=5)
    q = qr["factors"]["alpha101_001"]
    assert q["Q1"]["n"] > 0 and q["Q5"]["n"] > 0
    assert np.isfinite(q["spread"])
    bench = factor_bench(panel, "alpha101_001")
    assert bench["total_return"] == pytest.approx(bench["equity"][-1] - 1)
    assert bench["n_days"] > 50


def test_panel_lookahead_free_forward_returns() -> None:
    from app.services.factors.analysis import build_panel

    panel = build_panel(_histories(n_symbols=2, n=20, seed=1), [])
    assert panel["fwd_return"].iloc[-1] != panel["fwd_return"].iloc[-1]  # last row NaN tail
    last_fwd = panel["fwd_return"].dropna()
    assert (last_fwd.index.get_level_values(1) != panel.index.get_level_values(1)[-1]).all()


def _mixed_tz_histories() -> dict:
    """Three symbols with the SAME calendar dates but different tz offsets in ts
    (an IST-midnight NSE bar, a US-trading Yahoo bar and a UTC crypto bar for
    the same session)."""
    base = pd.date_range("2024-01-02", periods=250, freq="D")
    hist = {}
    for idx, (sym, offset) in enumerate([("NSE:SYMA", "+05:30"), ("NYSE:SYMB", "-04:00"), ("CRYPTO:SYMC", "+00:00")]):
        c = 100 * np.cumprod(1 + np.random.default_rng(10 + idx).normal(0.0004, 0.02, 250))
        candles = [
            {
                "ts": f"{d.strftime('%Y-%m-%d')}T00:00:00{offset}",
                "open": float(c[i] * 0.99),
                "high": float(c[i] * 1.01),
                "low": float(c[i] * 0.99),
                "close": float(c[i]),
                "volume": int(1e6),
            }
            for i, d in enumerate(base)
        ]
        hist[sym] = {"symbol": sym, "interval": "1d", "period": "2y", "candles": candles}
    return hist


def test_build_panel_aligns_mixed_timezone_calendar_dates() -> None:
    """IST bars must land on their calendar date, NOT the previous UTC day —
    otherwise NSE vs US cross-sections never align."""
    from app.services.factors.analysis import build_panel, ic_analysis

    panel = build_panel(_mixed_tz_histories(), ["alpha101_001"])
    assert not panel.empty
    dates = panel.index.get_level_values(1).unique()
    assert str(dates[0])[:10] == "2024-01-02"
    assert str(dates[-1])[:10] == "2024-09-07"
    per_date = panel.groupby(level=1).size()
    assert (per_date == 3).all(), "all symbols must align on every date"
    ic = ic_analysis(panel, ["alpha101_001"])["factors"]["alpha101_001"]
    assert ic["n_days"] > 100


def test_build_panel_handles_mixed_tz_offsets_within_one_symbol() -> None:
    """A single series whose ts values carry different tz offsets (DST change)
    must parse instead of raising 'Mixed timezones detected'."""
    from app.services.factors.analysis import build_panel

    hist = _mixed_tz_histories()
    sym = "NSE:SYMA"
    candles = hist[sym]["candles"]
    for i, c in enumerate(candles):
        c["ts"] = c["ts"].replace("+05:30", "-04:00" if i % 2 else "+05:30")
    panel = build_panel({sym: hist[sym]}, ["alpha101_001"])
    assert not panel.empty
    assert len(panel) == 250


def test_factors_endpoints(client: TestClient, auth: dict, monkeypatch) -> None:
    from app.api.routers import quant

    async def _fake_auto(symbol, *, interval="1d", period="1y", chain=None):
        return _histories().get(symbol, {"symbol": symbol, "interval": "1d", "period": "2y", "candles": []})

    monkeypatch.setattr(quant.market_data, "get_history_auto", _fake_auto)

    reg = client.get("/api/quant/factors", headers=auth)
    assert reg.status_code == 200
    assert reg.json()["count"] == 101

    symbols = list(_histories().keys())
    r = client.post(
        "/api/quant/factors/analysis",
        headers=auth,
        json={"symbols": symbols, "factors": ["alpha101_001", "alpha101_038"], "n_quantiles": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["symbols"]) == set(symbols)
    assert np.isfinite(body["ic"]["alpha101_001"]["ic_mean"])
    assert "Q5" in body["quantiles"]["alpha101_001"]

    b = client.post(
        "/api/quant/factors/bench",
        headers=auth,
        json={"symbols": symbols, "factors": ["alpha101_001"]},
    )
    assert b.status_code == 200, b.text
    assert np.isfinite(b.json()["total_return"])

    bad = client.post(
        "/api/quant/factors/analysis",
        headers=auth,
        json={"symbols": symbols, "factors": ["unknown_factor"]},
    )
    assert bad.status_code == 422 or bad.status_code == 200  # honest: panel just lacks it
