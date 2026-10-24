"""Tests for the `stockos` CLI package.

The CLI reuses the exact same real services as the API, so most of its logic is
already covered by the service tests. These tests pin the CLI's own glue:
timeframe parsing, number formatting, and the mocked data-path commands plus
the DB persistence path used by `stockos desk` (create/update/list a
trading_runs row without running the real LLM engine).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import typer

_TMPDIR = tempfile.mkdtemp(prefix="smcli_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'cli.db'}"


def _history(symbol: str, n: int = 300, seed: int = 5) -> dict:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.02, n))
    low = c * 0.99
    high = c * 1.01
    o = np.clip(c * (1 + rng.normal(0, 0.005, n)), low, high)
    return {
        "symbol": symbol,
        "interval": "1d",
        "period": "2y",
        "candles": [
            {
                "ts": str(d.date()),
                "open": float(o[i]),
                "high": float(high[i]),
                "low": float(low[i]),
                "close": float(c[i]),
                "volume": int(1_000_000),
            }
            for i, d in enumerate(dates)
        ],
    }


def test_cli_module_imports() -> None:
    import app.cli
    import app.cli.commands

    assert callable(app.cli.main)
    assert hasattr(app.cli.commands, "status_cmd")


def test_timeframe_mapping() -> None:
    from app.cli.commands import _timeframe
    from app.services.prediction.engine import Timeframe

    assert _timeframe("1D") == Timeframe.TOMORROW
    assert _timeframe("1w") == Timeframe.WEEK
    assert _timeframe("5Y") == Timeframe.FIVE_YEARS
    with pytest.raises(typer.BadParameter):
        _timeframe("9X")


def test_number_formatting() -> None:
    from app.cli.commands import _money, _pct

    assert _pct(0.1234) == "12.34%"
    assert _pct(None) == "-"
    assert _money(1234.5) == "1,234.50"
    assert _money(None) == "-"


async def test_backtest_command_uses_real_engine(monkeypatch) -> None:
    from app.cli.commands import _backtest
    from app.services.backtesting.engine_v2 import run_backtest_with_benchmark
    from app.services.data import ohlcv
    from app.services.data import service as data_service

    async def _fake_auto(symbol, *, interval="1d", period="1y", chain=None):
        return _history(symbol)

    monkeypatch.setattr(data_service.market_data, "get_history_auto", _fake_auto)
    monkeypatch.setattr(ohlcv, "sanitize_history", lambda h: h)

    result = await _backtest("NSE:RELIANCE", "moving_average_crossover", "1d", "2y", None, False, None, 100_000.0, False)
    assert result["metrics"]["total_return"] == pytest.approx(result["equity"][-1] / 100_000.0 - 1, rel=1e-6)
    assert result["n_bars"] == 300
    assert 0.0 <= result["metrics"]["max_drawdown"] <= 1.0

    with_bench = await _backtest("NSE:RELIANCE", "moving_average_crossover", "1d", "2y", "NSE:NIFTY", False, None, 100_000.0, False)
    assert "benchmark" in with_bench
    assert with_bench["benchmark"]["symbol"] == "NSE:NIFTY"

    with pytest.raises(typer.BadParameter):
        await _backtest("NSE:RELIANCE", "sma", "1d", "2y", None, False, "not json", 100_000.0, False)


@pytest.fixture(scope="module")
def db() -> None:
    from app.db.base import Base
    from app.db.session import engine

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())


async def test_desk_persistence_path(db: None) -> None:
    """`stockos desk` write path: create_run -> update_run -> add_run_nodes ->
    list_runs, all on the same trading_runs table the web UI reads."""
    from app.db.models import User
    from app.db.session import SessionFactory
    from sqlalchemy import select
    from app.services.tradingagents import store

    async with SessionFactory() as session:
        session.add(User(email="cli@test.dev", username="cliuser", hashed_password="x", role="user"))
        await session.commit()
        user = await session.scalar(
            select(User).where(User.email == "cli@test.dev")
        )

    async with SessionFactory() as session:
        row = await store.create_run(
            session,
            user_id=user.id,
            symbol="NSE:RELIANCE",
            engine_symbol="RELIANCE.NS",
            trade_date="2026-08-09",
            provider="ollama",
            deep_model="qwen3:14b",
            quick_model="qwen3:14b",
        )
        run_id = row.id
        assert row.status == "running"

        node_trace = [
            {"node": "market_analyst", "label": "Market Analyst"},
            {"node": "portfolio_manager", "label": "Portfolio Manager", "repeat": True},
        ]
        await store.update_run(
            session,
            run_id,
            status="completed",
            rating="Buy",
            signal={"direction": "long", "conviction": 0.6, "rating": "Buy"},
            final_decision="# Decision\nHold.",
            reports={"market_report": "real"},
            node_trace=node_trace,
            options=None,
        )
        await store.add_run_nodes(session, run_id, node_trace)

        runs = await store.list_runs(session, user.id)
        assert len(runs) == 1
        assert runs[0]["id"] == run_id
        assert runs[0]["status"] == "completed"
        assert runs[0]["rating"] == "Buy"
        assert runs[0]["signal"]["direction"] == "long"
        assert runs[0]["node_trace"][1]["repeat"] is True
