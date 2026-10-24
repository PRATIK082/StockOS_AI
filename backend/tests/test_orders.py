"""Comprehensive tests for the order management API routes.

Covers: preview, submit, kill-switch, cancel-all, square-off, list, detail.
Uses a mock quote to avoid external market data calls.
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
        json={"email": "orders@test.dev", "username": "orderuser", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        # Already registered from a prior run - log in instead
        login = client.post(
            "/api/auth/login",
            json={"identifier": "orderuser", "password": "secret123"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


def _mock_quote(monkeypatch):
    """Monkeypatch PaperBroker.quote to return a stable fake quote."""

    async def fake_quote(self, symbol):
        from app.brokers.interface import BrokerQuote, BrokerSide
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


# ---- Auth tests ----


def test_orders_requires_auth(client):
    """Unauthenticated requests must be rejected."""
    assert client.post("/api/v1/orders/preview").status_code == 401
    assert client.post("/api/v1/orders/submit").status_code == 401
    assert client.get("/api/v1/orders").status_code == 401
    assert client.post("/api/v1/orders/kill-switch").status_code == 401
    assert client.post("/api/v1/orders/cancel-all").status_code == 401
    assert client.post("/api/v1/orders/square-off").status_code == 401


# ---- Preview tests ----


def test_preview_valid_order(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/preview",
        json={"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 10},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "NSE:RELIANCE"
    assert body["side"] == "BUY"
    assert body["quantity"] == 10
    assert body["status"] == "preview"
    assert body["estimated_fill"] == 1500.0
    assert body["price"] == 1500.0


def test_preview_sell_order(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/preview",
        json={"symbol": "NSE:TCS", "side": "SELL", "quantity": 5},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["side"] == "SELL"


def test_preview_empty_symbol_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/orders/preview",
        json={"symbol": "", "side": "BUY", "quantity": 1},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_preview_missing_symbol_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/orders/preview",
        json={"side": "BUY", "quantity": 1},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_preview_zero_quantity_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/orders/preview",
        json={"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 0},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_preview_negative_quantity_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/orders/preview",
        json={"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": -5},
        headers=auth_headers,
    )
    assert r.status_code == 422


# ---- Submit tests ----


def test_submit_buy_order(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/submit",
        json={"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 10},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "filled"
    assert body["symbol"] == "NSE:RELIANCE"
    assert body["side"] == "BUY"
    assert body["quantity"] == 10
    assert body["fill_price"] == 1500.0
    assert body["order_id"] is not None


def test_submit_sell_order(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/submit",
        json={"symbol": "NSE:INFY", "side": "SELL", "quantity": 5},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "filled"
    assert body["side"] == "SELL"


def test_submit_with_limit_price(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/submit",
        json={"symbol": "NSE:TCS", "side": "BUY", "quantity": 5, "price": 1490.0, "order_type": "LIMIT"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "filled"
    assert body["fill_price"] is not None


def test_submit_empty_symbol_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/orders/submit",
        json={"symbol": "", "side": "BUY", "quantity": 1},
        headers=auth_headers,
    )
    assert r.status_code == 422


# ---- Order listing ----


def test_list_orders_after_submit(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)

    # Submit two orders
    client.post(
        "/api/v1/orders/submit",
        json={"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 2},
        headers=auth_headers,
    )
    client.post(
        "/api/v1/orders/submit",
        json={"symbol": "NSE:TCS", "side": "BUY", "quantity": 3},
        headers=auth_headers,
    )

    r = client.get("/api/v1/orders", headers=auth_headers)
    assert r.status_code == 200
    orders = r.json()
    assert len(orders) >= 2
    symbols = {o["symbol"] for o in orders}
    assert "NSE:RELIANCE" in symbols
    assert "NSE:TCS" in symbols


def test_order_detail(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)

    # Submit and get the DB id
    r = client.post(
        "/api/v1/orders/submit",
        json={"symbol": "NSE:HDFCBANK", "side": "BUY", "quantity": 1},
        headers=auth_headers,
    )
    assert r.status_code == 201
    db_id = r.json()["id"]

    # Fetch detail using DB id
    r2 = client.get(f"/api/v1/orders/{db_id}", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["symbol"] == "NSE:HDFCBANK"


# ---- Kill switch ----


def test_kill_switch(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post("/api/v1/orders/kill-switch", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["message"] == "Kill switch executed"
    assert "positions_square_off" in body


# ---- Cancel all ----


def test_cancel_all(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post("/api/v1/orders/cancel-all", headers=auth_headers)
    assert r.status_code == 200
    assert "orders_cancelled" in r.json()


# ---- Square off ----


def test_square_off(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post("/api/v1/orders/square-off", headers=auth_headers)
    assert r.status_code == 200
    assert "positions_closed" in r.json()
