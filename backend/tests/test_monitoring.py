"""Tests for Phase 9a: monitoring middleware + latency/traffic/health routes."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

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
        json={"email": "mon@t.dev", "username": "monuser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_middleware_records_requests(client: TestClient, auth: dict) -> None:
    assert client.get("/healthz").status_code == 200
    rows = client.get("/api/monitoring/traffic", headers=auth).json()["routes"]
    hits = [r for r in rows if "healthz" in r["route"]]
    assert hits and hits[0]["count"] >= 1
    assert hits[0]["errors"] == 0


def test_latency_percentiles_sane(client: TestClient, auth: dict) -> None:
    for _ in range(3):
        assert client.get("/healthz").status_code == 200
    rows = client.get("/api/monitoring/latency", headers=auth).json()["routes"]
    entry = next(r for r in rows if "healthz" in r["route"])
    assert entry["count"] >= 3
    assert entry["avg_ms"] >= 0
    assert entry["p50_ms"] <= entry["p95_ms"]


async def test_prune_removes_only_old_rows() -> None:
    from app.core.metrics import prune_old_metrics
    from app.db.models.monitoring import RequestMetric
    from app.db.session import SessionFactory

    async with SessionFactory() as session:
        session.add(RequestMetric(route="/old", method="GET", status_code=200, duration_ms=1.0,
                                  created_at=datetime.utcnow() - timedelta(days=8)))
        session.add(RequestMetric(route="/new", method="GET", status_code=200, duration_ms=1.0,
                                  created_at=datetime.utcnow()))
        await session.commit()
        removed = await prune_old_metrics(session, days=7)
        assert removed >= 1
        remaining = (await session.execute(
            select(RequestMetric.route)
        )).scalars().all()
        assert "/old" not in remaining
        assert "/new" in remaining


def test_health_shape_and_no_secrets(client: TestClient, auth: dict) -> None:
    payload = client.get("/api/monitoring/health", headers=auth).json()
    assert payload["app"]
    assert payload["environment"]
    proc = payload["process"]
    for key in ("rss_mb", "threads", "fds"):
        assert proc[key] is None or proc[key] >= 0
    assert payload["database"]["kind"] in ("sqlite", "remote")
    assert "secret" not in json.dumps(payload).lower()


def test_monitoring_requires_auth(client: TestClient) -> None:
    assert client.get("/api/monitoring/traffic").status_code in (401, 403)
    assert client.get("/api/monitoring/health").status_code in (401, 403)
