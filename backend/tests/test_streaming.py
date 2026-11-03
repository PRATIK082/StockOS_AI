"""Tests for S4: streaming status/latest/market REST + quotes/market websockets."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


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
def token(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "stream@test.dev", "username": "streamuser", "password": "secret123"},
    )
    if r.status_code == 201:
        return r.json()["access_token"]
    assert r.status_code == 409, r.text
    login = client.post("/api/auth/login", json={"identifier": "streamuser", "password": "secret123"})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _mock_quotes(monkeypatch):
    """Deterministic quotes: TEST:A ok, anything else raises."""
    from app.services.data import service as data_service

    async def fake_get_quote(self, symbol, provider=None):
        if symbol == "TEST:A":
            return {"symbol": symbol, "price": 100.0, "previous_close": 99.0,
                    "day_change_pct": 1.01, "volume": 1000, "provider": "test"}
        raise RuntimeError(f"no feed for {symbol}")

    monkeypatch.setattr(data_service.MarketDataService, "get_quote", fake_get_quote)


@pytest.fixture(autouse=True)
def _clean_hub():
    from app.services.streaming.hub import hub

    hub._latest.clear()
    hub._last_error.clear()
    yield
    for queue in list(hub._subs):
        hub._subs.pop(queue, None)
    hub._latest.clear()
    hub._last_error.clear()


# ------------------------------------------------------------------ REST
def test_status_shape(client, auth_headers):
    r = client.get("/api/streaming/status", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("provider", "mode", "poll_interval_s", "symbols",
                "symbol_count", "subscribers", "latest_cached"):
        assert key in body, key


def test_status_requires_auth(client):
    r = client.get("/api/streaming/status")
    assert r.status_code == 401, r.text


def test_latest_ok_and_missing(client, auth_headers):
    r = client.get("/api/streaming/quotes/latest?symbols=TEST:A,TEST:BOGUS", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quotes"]["TEST:A"]["price"] == 100.0
    assert body["quotes"]["TEST:BOGUS"] is None
    assert "TEST:BOGUS" in body["missing"]
    assert "TEST:A" not in body["missing"]


def test_latest_empty_symbols_400(client, auth_headers):
    r = client.get("/api/streaming/quotes/latest", headers=auth_headers)
    assert r.status_code == 400, r.text


def test_market_shape(client, auth_headers):
    r = client.get("/api/streaming/market", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["is_open"], bool)
    for key in ("reason", "server_time_ist", "next_trading_day"):
        assert key in body, key


# ------------------------------------------------------------------ WS
def test_ws_no_token_4401(client):
    # Accept-then-close: connect succeeds, the 4401 arrives as a close frame
    # (pre-accept close hides the code from real browsers as HTTP 403/1006).
    with client.websocket_connect("/api/streaming/quotes?symbols=TEST:A") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_bad_token_4401(client):
    with client.websocket_connect("/api/streaming/quotes?symbols=TEST:A&token=bogus") as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_snapshot_tick_unsubscribe(client, token):
    with client.websocket_connect(
        f"/api/streaming/quotes?symbols=TEST:A&interval_ms=500&token={token}"
    ) as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["symbols"] == ["TEST:A"]
        # Poll loop (2s hub interval) delivers a tick for TEST:A.
        tick = ws.receive_json()
        assert tick["type"] == "tick"
        assert tick["tick"]["symbol"] == "TEST:A"
        assert tick["tick"]["price"] == 100.0
        assert "ts" in tick["tick"]
        ws.send_json({"action": "unsubscribe", "symbols": ["TEST:A"]})
        ack = ws.receive_json()
        assert ack["type"] == "unsubscribed"
        assert ack["symbols"] == []
