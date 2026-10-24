"""API tests using an isolated temp SQLite database."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Point the app at a throwaway DB before importing anything app-related.
_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    # The throwaway DB has no schema (Alembic migrations target the real DB);
    # create tables directly so the API tests can run standalone.
    import asyncio
    from app.db.base import Base
    from app.db.session import engine

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())

    with TestClient(app) as c:
        yield c


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_providers_endpoint(client: TestClient) -> None:
    r = client.get("/api/market/providers")
    assert r.status_code == 200
    assert "yahoo" in r.json()
    assert "nse" in r.json()
    assert "tradingview" in r.json()


def test_provider_status_endpoint(client: TestClient) -> None:
    r = client.get("/api/market/status")
    assert r.status_code == 200
    body = r.json()
    for name in ("yahoo", "nse", "tradingview"):
        info = body[name]
        assert info["reachable"] in (True, False)
        assert "exchanges" in info and "capabilities" in info
        assert isinstance(info["default_for"], list)
    # NSE is routed to TradingView by default for the India options chain.
    assert "NSE" in body["tradingview"]["default_for"]


def test_register_login_me(client: TestClient) -> None:
    reg = client.post(
        "/api/auth/register",
        json={"email": "t@t.dev", "username": "tester", "password": "secret123"},
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    assert token

    bad = client.post(
        "/api/auth/login", json={"identifier": "t@t.dev", "password": "wrong"}
    )
    assert bad.status_code == 401

    good = client.post(
        "/api/auth/login", json={"identifier": "tester", "password": "secret123"}
    )
    assert good.status_code == 200

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "tester"

    noauth = client.get("/api/auth/me")
    assert noauth.status_code == 401


def test_watchlist_flow(client: TestClient) -> None:
    token = client.post(
        "/api/auth/register",
        json={"email": "w@t.dev", "username": "watcher", "password": "secret123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wl = client.post("/api/watchlist", headers=headers, json={"name": "Core"})
    assert wl.status_code == 201
    wl_id = wl.json()["id"]

    upd = client.patch(
        f"/api/watchlist/{wl_id}/symbols",
        headers=headers,
        json={"symbol": "NYSE:AAPL", "action": "add"},
    )
    assert upd.status_code == 200
    assert upd.json()["symbols"] == ["NYSE:AAPL"]

    listed = client.get("/api/watchlist", headers=headers)
    assert listed.json()[0]["symbols"] == ["NYSE:AAPL"]


def test_invalid_history_period_rejected(client: TestClient) -> None:
    r = client.get("/api/market/history/NSE:RELIANCE?period=abc")
    assert r.status_code == 422


def test_option_positions_flow(client: TestClient) -> None:
    token = client.post(
        "/api/auth/register",
        json={"email": "o@t.dev", "username": "optioner", "password": "secret123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Unauthenticated -> 401
    assert client.get("/api/options/positions").status_code == 401

    # Empty list
    listed = client.get("/api/options/positions", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == []

    # Add a CALL position
    added = client.post(
        "/api/options/positions",
        headers=headers,
        json={
            "symbol": "NSE:RELIANCE",
            "option_type": "CE",
            "strike": 1400.0,
            "expiry": "2026-08-28",
            "quantity": 25,
            "premium": 12.5,
        },
    )
    assert added.status_code == 201
    pos = added.json()
    assert pos["option_type"] == "CALL"
    assert pos["symbol"] == "NSE:RELIANCE"
    assert pos["strike"] == 1400.0

    # Bad option type -> 422
    bad = client.post(
        "/api/options/positions",
        headers=headers,
        json={
            "symbol": "NYSE:AAPL",
            "option_type": "STRADDLE",
            "strike": 200.0,
            "expiry": "2026-08-28",
        },
    )
    assert bad.status_code == 422

    # Add a PUT and verify list ordering + delete
    client.post(
        "/api/options/positions",
        headers=headers,
        json={
            "symbol": "NYSE:AAPL",
            "option_type": "PUT",
            "strike": 180.0,
            "expiry": "2026-09-18",
            "quantity": 10,
            "premium": 4.2,
        },
    )
    listed = client.get("/api/options/positions", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    types = {p["option_type"] for p in listed.json()}
    assert types == {"CALL", "PUT"}

    delete = client.delete(f"/api/options/positions/{pos['id']}", headers=headers)
    assert delete.status_code == 204
    assert client.get("/api/options/positions", headers=headers).json()[0]["option_type"] == "PUT"

    missing = client.delete("/api/options/positions/does-not-exist", headers=headers)
    assert missing.status_code == 404


def test_prediction_history_flow(client: TestClient) -> None:
    token = client.post(
        "/api/auth/register",
        json={"email": "ph@t.dev", "username": "historian", "password": "secret123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Unauthenticated -> 401
    assert client.get("/api/predictions").status_code == 401

    # Empty list
    assert client.get("/api/predictions", headers=headers).json() == []

    # Save a prediction, verify it round-trips with the payload intact
    payload = {"symbol": "NSE:NIFTY", "predicted_price": 25250.5, "action": "BUY", "factors": {}}
    saved = client.post("/api/predictions", headers=headers, json={"symbol": "NSE:NIFTY", "timeframe": "1W", "payload": payload})
    assert saved.status_code == 201
    row = saved.json()
    assert row["symbol"] == "NSE:NIFTY"
    assert row["timeframe"] == "1W"
    assert row["payload"]["predicted_price"] == 25250.5

    # List is newest-first and user-scoped
    listed = client.get("/api/predictions", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["id"] == row["id"]

    # Delete works; a second user cannot see/delete someone else's rows
    other = client.post(
        "/api/auth/register",
        json={"email": "other@t.dev", "username": "otherone", "password": "secret123"},
    ).json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other}"}
    assert client.get("/api/predictions", headers=other_headers).json() == []
    assert client.delete(f"/api/predictions/{row['id']}", headers=other_headers).status_code == 404

    deleted = client.delete(f"/api/predictions/{row['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/predictions", headers=headers).json() == []


def test_option_premium_history_builds_series(client: TestClient, monkeypatch) -> None:
    """Regression: the premium series must be built from real candle history.

    Previously `candles = (history or {}).get("candles") or history if
    isinstance(history, list) else []` parsed as `(...) if isinstance(...) else
    []`, so a dict history ALWAYS yielded an empty candle list and the premium
    chart 404'd with "No underlying history" for every symbol.
    """
    from app.api.routers import analysis as analysis_router

    async def fake_chain(symbol: str, expiry: str | None = None, provider: str | None = None) -> dict:
        return {
            "symbol": "NSE:TCS",
            "expiry": "2026-08-25",
            "expiries": ["2026-08-25"],
            "spot_price": 100.0,
            "calls": [
                {
                    "strike": 90.0, "iv": 0.2, "delta": 0.8, "gamma": 0.01,
                    "theta": -0.5, "vega": 1.0,
                }
            ],
            "puts": [],
        }

    async def fake_history(symbol: str, interval: str = "1d", period: str = "1y", chain: list[str] | None = None) -> dict:
        return {
            "symbol": symbol,
            "candles": [
                {"ts": "2026-07-01T00:00:00+05:30", "close": 100.0},
                {"ts": "2026-07-02T00:00:00+05:30", "close": 110.0},
                {"ts": "2026-07-03T00:00:00+05:30", "close": 105.0},
            ],
        }

    monkeypatch.setattr(analysis_router.market_data, "get_option_chain", fake_chain)
    monkeypatch.setattr(analysis_router.market_data, "get_history_auto", fake_history)

    r = client.get(
        "/api/analysis/options/premium/NSE:TCS?strike=90&option_type=CE&expiry=2026-08-25&interval=1d&period=1mo"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["series"]) == 3
    assert all(p["premium"] > 0 for p in body["series"])
    assert body["series"][0]["spot"] == 100.0
    assert body["strike"] == 90.0
    assert body["option_type"] == "CALL"
