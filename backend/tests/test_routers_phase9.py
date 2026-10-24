"""Tests for Phase 9: swarm + quantlib routers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


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
        json={"email": "ql@t.dev", "username": "quantlibuser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_quantlib_risk_endpoint(client: TestClient, auth: dict) -> None:
    r = client.post(
        "/api/quantlib/risk",
        headers=auth,
        json={"returns": [0.01, -0.02, 0.03, -0.01, 0.02, 0.0, -0.03, 0.011, 0.021, -0.021, 0.012, 0.001] * 50, "level": 0.06, "threshold_pct": 0.95},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n"] == 600
    assert body["parametric_var"]["var"] > 0
    assert body["evt_var"]["var"] > 0


def test_quantlib_portfolio_endpoint(client: TestClient, auth: dict) -> None:
    r = client.post(
        "/api/quantlib/portfolio",
        headers=auth,
        json={
            "method": "black_litterman",
            "returns_mean": {"A": 0.12, "B": 0.09},
            "cov": [[0.04, 0.01], [0.01, 0.03]],
            "market_weights": {"A": 0.6, "B": 0.4},
            "views": [{"assets": ["A"], "weights": [1.0], "return": 0.15}],
        },
    )
    assert r.status_code == 200
    assert set(r.json()["optimal_weights"]) == {"A", "B"}
    br = client.post(
        "/api/quantlib/portfolio",
        headers=auth,
        json={
            "method": "brinson",
            "portfolio_returns": {"A": 0.08, "B": 0.04},
            "benchmark_returns": {"A": 0.06, "B": 0.05},
            "portfolio_weights": {"A": 0.6, "B": 0.4},
            "benchmark_weights": {"A": 0.5, "B": 0.5},
        },
    )
    assert br.status_code == 200 and br.json()["totals"]["active_return"] is not None


def test_quantlib_cashflow_and_options(client: TestClient, auth: dict) -> None:
    irr = client.post("/api/quantlib/cashflow", headers=auth, json={"tool": "irr", "amounts": [-100, 30, 30, 30, 30]})
    assert irr.status_code == 200 and 0 < irr.json()["result"] < 1
    g = client.post(
        "/api/quantlib/options",
        headers=auth,
        json={"tool": "greeks", "spot": 100, "strike": 100, "time_to_expiry": 0.25, "volatility": 0.25},
    )
    assert g.status_code == 200 and g.json()["delta"] > 0


def test_swarm_endpoints(client: TestClient, auth: dict, monkeypatch) -> None:
    from app.services.scheduler import runner

    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(5)
    dates = pd.date_range("2025-01-01", periods=200, freq="D")
    out = {}
    for j, sym in enumerate(["SW0", "SW1", "SW2"]):
        c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.02, 200))
        out[sym] = {
            "symbol": sym,
            "interval": "1d",
            "period": "1y",
            "candles": [{"ts": str(d.date()), "open": float(c[i]), "high": float(c[i] * 1.01), "low": float(c[i] * 0.99), "close": float(c[i]), "volume": 1_000_000} for i, d in enumerate(dates)],
        }

    async def _auto(symbol, *, interval="1d", period="2y", chain=None):
        return out[symbol]

    monkeypatch.setattr(runner.market_data, "get_history_auto", _auto)
    presets = client.get("/api/swarm/presets", headers=auth).json()
    assert presets["count"] == 30
    dag = client.get("/api/swarm/presets/quant-sweep", headers=auth).json()
    assert len(dag["nodes"]) == 4
    run = client.post("/api/swarm/run", headers=auth, json={"preset": "quant-sweep", "symbols": ["SW0", "SW1", "SW2"]})
    assert run.status_code == 200, run.text
    assert "decide" in run.json()["nodes"]
    assert client.post("/api/swarm/run", headers=auth, json={"preset": "nope", "symbols": ["SW0"]}).status_code == 422
