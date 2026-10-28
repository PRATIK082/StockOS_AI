"""Tests for the Historify DuckDB warehouse routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import asyncio
    from app.main import app
    from app.db.base import Base
    from app.db.session import engine

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "historify@test.dev", "username": "historifyuser", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post("/api/auth/login", json={"identifier": "historifyuser", "password": "secret123"})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


def test_historify_ingest_and_query(client, auth_headers):
    records = [
        {"symbol": "NSE:TCS", "exchange": "NSE", "interval": "1d", "ts": "2024-01-01", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000, "provider": "test"},
        {"symbol": "NSE:TCS", "exchange": "NSE", "interval": "1d", "ts": "2024-01-02", "open": 105, "high": 115, "low": 100, "close": 112, "volume": 1200, "provider": "test"},
    ]
    r = client.post("/api/historify/ingest", json={"records": records}, headers=auth_headers)
    assert r.status_code == 201, r.text
    assert r.json()["ingested"] == 2

    r2 = client.get("/api/historify/status", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["rows"] >= 2

    r3 = client.get("/api/historify/query", params={"symbol": "NSE:TCS", "interval": "1d", "limit": 10}, headers=auth_headers)
    assert r3.status_code == 200
    rows = r3.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["symbol"] == "NSE:TCS"
