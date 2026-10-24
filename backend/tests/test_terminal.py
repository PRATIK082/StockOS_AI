"""Tests for the trading-terminal routes (positions, analytics, journal, tradebot).

Uses a mock quote to avoid external market data calls, mirroring test_orders.py.
"""

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
    """Register a user and return auth headers. Handles already-registered."""
    r = client.post(
        "/api/auth/register",
        json={"email": "terminal@test.dev", "username": "terminaluser", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "terminaluser", "password": "secret123"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


def _mock_quote(monkeypatch):
    """Monkeypatch PaperBroker.quote to return a stable fake quote."""

    async def fake_quote(self, symbol):
        from app.brokers.interface import BrokerQuote
        from decimal import Decimal
        from datetime import datetime

        return BrokerQuote(
            symbol=symbol,
            exchange=symbol.split(":")[0] if ":" in symbol else "NSE",
            last_price=Decimal("1500.00"),
            bid=Decimal("1499.00"),
            ask=Decimal("1501.00"),
            volume=100000,
            open=Decimal("1490.00"),
            high=Decimal("1510.00"),
            low=Decimal("1485.00"),
            close=Decimal("1495.00"),
            timestamp=datetime.utcnow(),
        )

    from app.brokers.paper import PaperBroker
    monkeypatch.setattr(PaperBroker, "quote", fake_quote)


# ---- Auth ---------------------------------------------------------------


def test_terminal_requires_auth(client):
    assert client.get("/api/terminal/positions").status_code == 401
    assert client.get("/api/terminal/analytics").status_code == 401
    assert client.get("/api/terminal/journal").status_code == 401
    assert client.get("/api/terminal/tradebot").status_code == 401


# ---- Positions ----------------------------------------------------------


def test_positions_shape(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.get("/api/terminal/positions", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "positions" in body
    assert "summary" in body
    assert body["summary"]["count"] >= 0
    assert "unrealised_pnl" in body["summary"]


def test_positions_after_buy(client, auth_headers, monkeypatch):
    # Use a symbol unique to this suite so earlier order tests in the same
    # process never collide with PaperBroker's in-memory state or the
    # duplicate-order-per-day guard.
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/submit",
        json={"symbol": "NSE:WIPRO", "side": "BUY", "quantity": 10},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r2 = client.get("/api/terminal/positions", headers=auth_headers)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    matches = [p for p in body["positions"] if p["symbol"] == "NSE:WIPRO"]
    assert len(matches) == 1
    p = matches[0]
    assert p["quantity"] == 10
    assert p["average_price"] > 0
    assert p["last_price"] > 0
    assert p["market_value"] > 0


# ---- Analytics ----------------------------------------------------------


def test_analytics_shape(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.get("/api/terminal/analytics", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "portfolio" in body
    assert "equity_curve" in body
    assert isinstance(body["equity_curve"], list)
    assert "summary" in body
    assert "risk" in body
    assert body["summary"]["base_capital"] > 0
    assert body["risk"]["execution_mode"] == "PAPER"


# ---- Journal ------------------------------------------------------------


def test_journal_create_list_delete(client, auth_headers):
    r = client.post(
        "/api/terminal/journal",
        json={"symbol": "NSE:TCS", "side": "BUY", "rationale": "SMA cross", "pnl": 250.0, "outcome": "win", "tags": ["trend"]},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    jid = r.json()["id"]

    r2 = client.get("/api/terminal/journal", headers=auth_headers)
    assert r2.status_code == 200
    entries = r2.json()["entries"]
    assert any(e["id"] == jid and e["symbol"] == "NSE:TCS" for e in entries)

    r3 = client.delete(f"/api/terminal/journal/{jid}", headers=auth_headers)
    assert r3.status_code == 200
    assert r3.json()["deleted"] is True

    r4 = client.get("/api/terminal/journal", headers=auth_headers)
    assert all(e["id"] != jid for e in r4.json()["entries"])


def test_journal_requires_rationale(client, auth_headers):
    r = client.post(
        "/api/terminal/journal",
        json={"symbol": "NSE:TCS", "side": "BUY", "rationale": "", "pnl": 0, "outcome": "open", "tags": []},
        headers=auth_headers,
    )
    assert r.status_code == 422


# ---- Tradebot -----------------------------------------------------------


def test_tradebot_default_paused(client, auth_headers):
    r = client.get("/api/terminal/tradebot", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["mode"] == "PAPER"


def test_tradebot_toggle(client, auth_headers):
    r = client.post("/api/terminal/tradebot/toggle", json={"enabled": True}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is True

    r2 = client.get("/api/terminal/tradebot", headers=auth_headers)
    assert r2.json()["enabled"] is True

    r3 = client.post("/api/terminal/tradebot/toggle", json={"enabled": False}, headers=auth_headers)
    assert r3.json()["enabled"] is False


def test_tradebot_execute(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/terminal/tradebot/execute",
        json={"symbol": "NSE:GRASIM", "side": "BUY", "quantity": 1},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "filled"
    assert body["symbol"] == "NSE:GRASIM"