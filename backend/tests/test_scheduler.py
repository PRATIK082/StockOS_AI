"""Tests for Phase 7: cron engine, IANA-tz schedule service, playbook runner."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
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
        json={"email": "sched@t.dev", "username": "scheduler", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_cron_next_occurrence() -> None:
    from app.services.scheduler.cron import CronError, next_occurrence, parse_cron

    spec = parse_cron("0 9 * * 1-5")  # 09:00 weekdays
    nxt = next_occurrence(spec, datetime(2026, 8, 7, 12, 0))  # Friday
    assert nxt == datetime(2026, 8, 10, 9, 0)  # next Monday
    spec2 = parse_cron("*/15 * * * *")
    assert next_occurrence(spec2, datetime(2026, 8, 7, 10, 0)) == datetime(2026, 8, 7, 10, 15)
    with pytest.raises(CronError):
        parse_cron("61 * * * *")  # out of range
    with pytest.raises(CronError):
        next_occurrence(parse_cron("0 0 30 2 *"), datetime(2026, 1, 1))  # Feb 30 never matches


def test_schedule_service_crud(client: TestClient) -> None:
    import asyncio

    from app.services.scheduler.service import scheduled_research_service

    async def _run() -> None:
        created = await scheduled_research_service.create(
            "u1",
            "Morning brief",
            {"type": "technical_summary", "symbols": ["NSE:RELIANCE"]},
            "0 9 * * 1-5",
            "Asia/Kolkata",
        )
        assert created["enabled"] is True and created["timezone"] == "Asia/Kolkata"
        assert created["next_run_at"]
        got = await scheduled_research_service.get("u1", created["id"])
        assert got is not None and got["playbook"]["type"] == "technical_summary"
        due = await scheduled_research_service.due_tasks(datetime(2030, 1, 1, tzinfo=timezone.utc))
        assert any(d["id"] == created["id"] for d in due)
        updated = await scheduled_research_service.update(
            "u1", created["id"], enabled=False, cron_expr="0 10 * * *"
        )
        assert updated["enabled"] is False and updated["cron_expr"] == "0 10 * * *"
        await scheduled_research_service.mark_run(created["id"], {"status": "done", "output": {"ok": 1}})
        runs = await scheduled_research_service.runs("u1", created["id"])
        assert runs and runs[0]["output"]["ok"] == 1
        assert await scheduled_research_service.delete("u1", created["id"]) is True
        assert await scheduled_research_service.delete("u1", created["id"]) is False

    asyncio.run(_run())


def _fake_histories() -> dict:
    import numpy as np

    rng = np.random.default_rng(11)
    n = 250
    dates = __import__("pandas").date_range("2025-01-01", periods=n, freq="D")
    out = {}
    for j, sym in enumerate(["SYM0", "SYM1", "SYM2", "SYM3"]):
        c = 100 * np.cumprod(1 + rng.normal(0.0004, 0.02, n))
        candles = [
            {
                "ts": str(d.date()),
                "open": float(c[i]),
                "high": float(c[i] * 1.01),
                "low": float(c[i] * 0.99),
                "close": float(c[i]),
                "volume": 1_000_000,
            }
            for i, d in enumerate(dates)
        ]
        out[sym] = {"symbol": sym, "interval": "1d", "period": "1y", "candles": candles}
    return out


@pytest.mark.asyncio
async def test_runner_technical_summary(monkeypatch) -> None:
    from app.services.scheduler import runner

    async def _auto(symbol, *, interval="1d", period="2y", chain=None):
        return _fake_histories()[symbol]

    monkeypatch.setattr(runner.market_data, "get_history_auto", _auto)
    result = await runner.run_playbook({"type": "technical_summary", "symbols": ["SYM0", "SYM1"]})
    assert "error" not in result
    assert result["verdict"]["rating"] in {"BUY", "SELL", "HOLD"}
    assert result["stats"]["SYM0"]["rsi"] > 0


@pytest.mark.asyncio
async def test_runner_swarm(monkeypatch) -> None:
    from app.services.scheduler import runner

    async def _auto(symbol, *, interval="1d", period="2y", chain=None):
        return _fake_histories()[symbol]

    monkeypatch.setattr(runner.market_data, "get_history_auto", _auto)
    result = await runner.run_playbook({"type": "swarm", "preset": "quant-sweep", "symbols": ["SYM0", "SYM1", "SYM2", "SYM3"]})
    assert "error" not in result
    for role in ["screen", "verify", "analyze", "decide"]:
        assert role in result["nodes"]


@pytest.mark.asyncio
async def test_runner_unknown_playbook() -> None:
    from app.services.scheduler import runner

    result = await runner.run_playbook({"type": "nope"})
    assert "error" in result


def test_schedule_endpoints(client: TestClient, auth: dict, monkeypatch) -> None:
    from app.services.scheduler import runner

    async def _auto(symbol, *, interval="1d", period="2y", chain=None):
        return _fake_histories()[symbol]

    monkeypatch.setattr(runner.market_data, "get_history_auto", _auto)
    r = client.get("/api/scheduled/presets", headers=auth)
    assert r.status_code == 200 and len(r.json()["presets"]) == 30
    r = client.post(
        "/api/scheduled",
        headers=auth,
        json={
            "name": "Daily",
            "cron_expr": "0 9 * * 1-5",
            "timezone": "Asia/Kolkata",
            "playbook": {"type": "technical_summary", "symbols": ["SYM0"]},
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r2 = client.post(f"/api/scheduled/{sid}/run", headers=auth)
    assert r2.status_code == 200 and "error" not in r2.json()
    runs = client.get(f"/api/scheduled/{sid}/runs", headers=auth).json()
    assert len(runs) == 1
    assert client.delete(f"/api/scheduled/{sid}", headers=auth).status_code == 200
    assert client.post("/api/scheduled", headers=auth, json={"name": "x", "cron_expr": "not cron", "playbook": {"type": "backtest", "symbol": "SYM0"}}).status_code == 422
