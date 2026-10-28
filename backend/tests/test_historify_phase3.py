"""Phase 3 Historify backend tests: watchlist, catalog, jobs, incremental, import/export, FNO."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

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
        json={"email": "hist3@test.dev", "username": "hist3user", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post("/api/auth/login", json={"identifier": "hist3user", "password": "secret123"})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


def test_watchlist_and_catalog(client, auth_headers):
    h = auth_headers
    r = client.post("/api/historify/watchlist", json={"symbol": "NSE:TCS"}, headers=h)
    assert r.status_code in (200, 201)
    listed = client.get("/api/historify/watchlist", headers=h)
    assert listed.status_code == 200
    assert any(w["symbol"] == "NSE:TCS" for w in listed.json())

    records = [
        {"symbol": "NSE:TCS", "exchange": "NSE", "interval": "1d", "ts": "2024-01-01", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000, "provider": "test"}
    ]
    assert client.post("/api/historify/ingest", json={"records": records}, headers=h).status_code == 201
    cat = client.get("/api/historify/catalog", headers=h)
    assert cat.status_code == 200
    assert any(c["symbol"] == "NSE:TCS" for c in cat.json())


def test_incremental_ingest(client, auth_headers):
    h = auth_headers
    records = [
        {"symbol": "NSE:TCS", "exchange": "NSE", "interval": "1d", "ts": "2024-01-01", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000, "provider": "test"},
        {"symbol": "NSE:TCS", "exchange": "NSE", "interval": "1d", "ts": "2024-01-02", "open": 105, "high": 115, "low": 100, "close": 112, "volume": 1200, "provider": "test"},
    ]
    r = client.post("/api/historify/ingest/incremental", json={"records": records}, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert "inserted" in body and "skipped" in body
    # second call should skip duplicates
    r2 = client.post("/api/historify/ingest/incremental", json={"records": records}, headers=h)
    assert r2.json()["skipped"] >= 1


def test_import_export_csv(client, auth_headers):
    h = auth_headers
    csvdata = "symbol,exchange,interval,ts,open,high,low,close,volume\nNSE:INFY,NSE,1d,2024-01-01,1,2,0.5,1.5,10\n"
    files = {"file": ("data.csv", csvdata, "text/csv")}
    r = client.post("/api/historify/import/csv", files=files, headers=h)
    assert r.status_code == 201
    assert r.json().get("inserted", 0) >= 1

    exp = client.get("/api/historify/export/json", params={"symbol": "NSE:INFY"}, headers=h)
    assert exp.status_code == 200
    assert len(exp.json().get("rows", [])) >= 1


def test_fno_metadata(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/historify/symbol-metadata",
        json={"symbol": "NIFTY24JAN20000CE", "exchange": "NFO", "instrument_type": "CE", "underlying": "NIFTY", "expiry": "2024-01-25", "strike": 20000, "lot_size": 50},
        headers=h,
    )
    assert r.status_code == 201
    assert client.get("/api/historify/fno/underlyings", headers=h).json() == ["NIFTY"] or "NIFTY" in client.get("/api/historify/fno/underlyings", headers=h).json()
    exps = client.get("/api/historify/fno/expiries", params={"underlying": "NIFTY"}, headers=h)
    assert "2024-01-25" in exps.json()
    contracts = client.get("/api/historify/fno/contracts", params={"underlying": "NIFTY"}, headers=h)
    assert len(contracts.json()) >= 1


def test_jobs_lifecycle(client, auth_headers):
    h = auth_headers
    r = client.post("/api/historify/jobs/download", json={"symbols": ["NSE:TCS"], "interval": "1d", "period": "1mo"}, headers=h)
    assert r.status_code == 201
    job_id = r.json()["id"]
    assert r.json()["status"] in ("queued", "running", "completed")

    jr = client.get(f"/api/historify/jobs/{job_id}", headers=h)
    assert jr.status_code == 200

    # pause/resume/cancel endpoints respond
    assert client.post(f"/api/historify/jobs/{job_id}/pause", headers=h).status_code == 200
    assert client.post(f"/api/historify/jobs/{job_id}/resume", headers=h).status_code == 200
    assert client.post(f"/api/historify/jobs/{job_id}/cancel", headers=h).status_code == 200

    lst = client.get("/api/historify/jobs", headers=h)
    assert lst.status_code == 200
    assert any(j["id"] == job_id for j in lst.json())


def test_gaps_and_status(client, auth_headers):
    h = auth_headers
    r = client.get("/api/historify/gaps", params={"symbol": "NSE:TCS"}, headers=h)
    assert r.status_code == 200
    assert "gaps" in r.json()
    st = client.get("/api/historify/status", headers=h)
    assert st.status_code == 200
    assert "rows" in st.json()
