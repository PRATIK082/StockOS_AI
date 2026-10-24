"""Tests for Phase 4: signal blending + factor portfolio backtest."""

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


def _histories(n_symbols: int = 6, n: int = 300, seed: int = 3) -> dict:
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
        json={"email": "sb@t.dev", "username": "signalblender", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _panel():
    from app.services.factors.analysis import build_panel

    return build_panel(_histories(), ["alpha101_001", "alpha101_038"])


def test_normalize_and_composite() -> None:
    from app.services.factors.blend import composite_signal, normalize

    panel = _panel()
    rank_s = normalize(panel["alpha101_001"], "rank")
    assert rank_s.min() >= 0 and rank_s.max() <= 1
    z = normalize(panel["alpha101_001"], "zscore")
    assert np.isfinite(z.fillna(0)).all()
    sig = composite_signal(panel, {"alpha101_001": 1.0, "alpha101_038": -0.5}, "rank")
    assert len(sig) == len(panel)
    assert np.isfinite(sig.fillna(0)).all()


def test_factor_portfolio_backtest() -> None:
    from app.services.factors.analysis import build_panel
    from app.services.factors.backtest import factor_portfolio_backtest
    from app.services.factors.blend import composite_signal

    panel = build_panel(_histories(), ["alpha101_001"])
    sig = composite_signal(panel, {"alpha101_001": 1.0})
    panel["composite"] = sig
    res = factor_portfolio_backtest(panel, "composite", n_quantiles=3, long_only=True)
    assert res["n_days"] > 20
    assert len(res["equity"]) == res["n_days"] + 1
    assert res["metrics"]["total_return"] == pytest.approx(res["equity"][-1] / 100_000 - 1)
    assert 0 <= res["metrics"]["max_drawdown"] <= 1
    ls = factor_portfolio_backtest(panel, "composite", n_quantiles=3, long_only=False)
    assert ls["n_days"] > 20 and np.isfinite(ls["metrics"]["sharpe_ratio"])


def test_blend_endpoint(client: TestClient, auth: dict, monkeypatch) -> None:
    from app.api.routers import quant

    async def _fake_auto(symbol, *, interval="1d", period="1y", chain=None):
        return _histories().get(symbol, {"symbol": symbol, "interval": "1d", "period": "2y", "candles": []})

    monkeypatch.setattr(quant.market_data, "get_history_auto", _fake_auto)
    symbols = list(_histories().keys())
    r = client.post(
        "/api/quant/signals/blend",
        headers=auth,
        json={
            "symbols": symbols,
            "weights": {"alpha101_001": 1.0, "alpha101_038": -0.5},
            "n_quantiles": 3,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metrics"]["total_return"] == pytest.approx(body["equity"][-1] / 100_000 - 1)
    assert body["weights"] == {"alpha101_001": 1.0, "alpha101_038": -0.5}
