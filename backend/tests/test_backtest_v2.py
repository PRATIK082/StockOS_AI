"""Tests for backtest engine v2 (fills, costs, metrics, validation, sandbox,
portfolio optimizers) and the wired API endpoint."""

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


def _synthetic_history(n: int = 300, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0006, 0.015, n))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    candles = [
        {
            "ts": str(d.date()),
            "open": float(open_[i]),
            "high": float(high[i]),
            "low": float(low[i]),
            "close": float(close[i]),
            "volume": int(1e6),
        }
        for i, d in enumerate(dates)
    ]
    return {"symbol": "TEST", "interval": "1d", "period": "2y", "candles": candles}


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
        json={"email": "bt@t.dev", "username": "backtester", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _engine_run(**kw) -> dict:
    from app.services.backtesting.engine_v2 import BacktestRequest, run_backtest
    from app.services.data.ohlcv import to_dataframe

    df = to_dataframe(_synthetic_history())
    req = BacktestRequest(symbol="TEST", **kw)
    return run_backtest(df, req)


def test_engine_equity_and_metrics() -> None:
    res = _engine_run(strategy="buy_and_hold")
    assert len(res["equity"]) == len(res["dates"]) == 300
    assert res["metrics"]["final_equity"] > 0
    assert res["metrics"]["total_return"] == pytest.approx(res["equity"][-1] / 100_000 - 1)
    assert 0 <= res["metrics"]["max_drawdown"] <= 1
    assert "trades" in res["metrics"]
    assert res["cost_config"]["buy_cost_pct"] > 0


def test_engine_no_lookahead_positions_shifted() -> None:
    from app.services.backtesting.engine_v2 import BacktestRequest, run_backtest
    from app.services.data.ohlcv import to_dataframe

    df = to_dataframe(_synthetic_history())
    req = BacktestRequest(symbol="TEST", strategy="macd_trend")
    res = run_backtest(df, req)
    assert len(res["positions"]) == len(df)
    assert all(p in (0, 1) for p in res["positions"])


def test_engine_filters_stale_strategy_params() -> None:
    """Foreign keys from another strategy must never crash the target fn."""
    from app.services.backtesting.engine_v2 import BacktestRequest, run_backtest
    from app.services.data.ohlcv import to_dataframe

    df = to_dataframe(_synthetic_history())
    # 'k' belongs to bollinger, 'lookback' to donchian, 'period' to rsi.
    stale = {"k": 2.5, "lookback": 50, "oversold": 25.0, "overbought": 75.0, "fast": 5}
    cases = ["rsi_mean_reversion", "donchian_breakout", "macd_trend", "bollinger_breakout"]
    for name in cases:
        res = run_backtest(df, BacktestRequest(symbol="TEST", strategy=name, params=dict(stale)))
        assert len(res["positions"]) == len(df)


def test_engine_validation_block() -> None:
    res = _engine_run(strategy="moving_average_crossover", params={"fast": 10, "slow": 30}, validate=True)
    assert "monte_carlo" in res
    assert res["monte_carlo"]["terminal_median"] > 0
    assert "bootstrap" in res
    assert "sharpe" in res["bootstrap"]
    assert "walk_forward" in res
    assert res["walk_forward"]["n_folds"] >= 2


def test_engine_custom_strategy_inline() -> None:
    code = (
        'def generate(data, params):\n'
        '    fast = params.get("fast", 20)\n'
        '    slow = params.get("slow", 50)\n'
        '    f = data["close"].rolling(fast).mean()\n'
        '    s = data["close"].rolling(slow).mean()\n'
        '    return (f > s).astype(int).fillna(0)\n'
    )
    res = _engine_run(strategy="custom", custom_code=code, params={"fast": 10, "slow": 30})
    assert set(res["positions"]) <= {0, 1}
    assert sum(res["positions"]) > 0


def test_engine_custom_strategy_malicious_rejected() -> None:
    from app.services.backtesting.sandbox import StrategySandboxError

    code = 'def generate(d, p):\n    import os\n    return [0] * len(d)\n'
    with pytest.raises(StrategySandboxError):
        _engine_run(strategy="custom", custom_code=code)


def test_metrics_finite_safe() -> None:
    from app.services.backtesting.metrics import compute_metrics, to_returns

    eq = np.array([1.0, np.nan, np.inf, 2.0, 3.0])
    m = compute_metrics(eq, to_returns(eq), interval="1d")
    assert np.isfinite(m["total_return"]) and np.isfinite(m["sharpe_ratio"])


def test_portfolio_optimizers_weight_sum_one() -> None:
    from app.services.backtesting.portfolio_engine import list_methods, optimize

    rng = np.random.default_rng(3)
    returns = pd.DataFrame({
        "A": rng.normal(0.001, 0.02, 250),
        "B": rng.normal(0.0008, 0.03, 250),
        "C": rng.normal(0.0005, 0.01, 250),
    })
    for method in list_methods():
        res = optimize(returns, method)
        w = res.as_dict()["weights"]
        assert set(w.keys()) == {"A", "B", "C"}
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-4)
        assert all(v >= 0 for v in w.values())


def test_sandbox_ast_validation() -> None:
    from app.services.backtesting.sandbox import validate_ast

    assert validate_ast('def generate(d, p):\n    return d["close"] * 2 > 100') == []
    bad = 'def generate(d, p):\n    return [x.__class__ for x in d]'
    assert any("attribute" in v for v in validate_ast(bad))
    bad2 = 'def generate(d, p):\n    return eval("1+1") * len(d)'
    assert any(v for v in validate_ast(bad2))


def test_backtest_endpoint(client: TestClient, auth: dict, monkeypatch) -> None:
    from app.api.routers import analysis

    async def _fake_auto(symbol, *, interval="1d", period="1y", chain=None):
        return _synthetic_history()

    monkeypatch.setattr(analysis.market_data, "get_history_auto", _fake_auto)
    r = client.post(
        "/api/analysis/backtest",
        headers=auth,
        json={
            "symbol": "TEST",
            "strategy": "moving_average_crossover",
            "params": {"fast": 10, "slow": 30},
            "run_validation": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "TEST"
    assert body["metrics"]["total_return"] == pytest.approx(body["equity"][-1] / 100_000 - 1)
    assert body["risk"]["exposure_time"] >= 0
    assert body["cost_config"]["round_trip_cost_pct"] > 0


def test_backtest_strategies_endpoint(client: TestClient, auth: dict) -> None:
    r = client.get("/api/analysis/backtest/strategies", headers=auth)
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["strategies"]}
    assert "moving_average_crossover" in names and "buy_and_hold" in names
    assert "min_variance" in r.json()["optimizers"]


def test_backtest_endpoint_unknown_strategy(client: TestClient, auth: dict, monkeypatch) -> None:
    from app.api.routers import analysis

    async def _fake_auto(symbol, *, interval="1d", period="1y", chain=None):
        return _synthetic_history()

    monkeypatch.setattr(analysis.market_data, "get_history_auto", _fake_auto)
    r = client.post(
        "/api/analysis/backtest",
        headers=auth,
        json={"symbol": "TEST", "strategy": "does_not_exist"},
    )
    assert r.status_code == 422


def test_engine_rejects_zero_window_with_friendly_message() -> None:
    """fast=0 (e.g. from a cleared form field) must fail with a human message,
    not pandas' 'min_periods 1 must be <= window 0'."""
    with pytest.raises(ValueError, match='"fast" must be between'):
        _engine_run(strategy="moving_average_crossover", params={"fast": 0, "slow": 50})


def test_engine_rejects_fast_not_below_slow() -> None:
    with pytest.raises(ValueError, match='must be smaller than "slow"'):
        _engine_run(strategy="moving_average_crossover", params={"fast": 50, "slow": 20})


def test_engine_rejects_non_integer_window() -> None:
    with pytest.raises(ValueError, match="whole number"):
        _engine_run(strategy="moving_average_crossover", params={"fast": 10.5, "slow": 50})


def test_engine_accepts_integral_float_window() -> None:
    res = _engine_run(strategy="moving_average_crossover", params={"fast": 10.0, "slow": 30.0})
    assert len(res["positions"]) == 300


def test_backtest_endpoint_zero_window_is_422_with_message(client: TestClient, auth: dict, monkeypatch) -> None:
    from app.api.routers import analysis

    async def _fake_auto(symbol, *, interval="1d", period="1y", chain=None):
        return _synthetic_history()

    monkeypatch.setattr(analysis.market_data, "get_history_auto", _fake_auto)
    r = client.post(
        "/api/analysis/backtest",
        headers=auth,
        json={"symbol": "TEST", "strategy": "moving_average_crossover", "params": {"fast": 0, "slow": 50}},
    )
    assert r.status_code == 422
    assert "fast" in r.json()["detail"]
    assert "min_periods" not in r.json()["detail"]
