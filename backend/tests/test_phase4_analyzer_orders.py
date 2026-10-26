"""Tests for Phase 4: analyzer mode + smart/basket/split orders + action center."""

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
        json={"email": "phase4@test.dev", "username": "phase4user", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post("/api/auth/login", json={"identifier": "phase4user", "password": "secret123"})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


def _mock_quote(monkeypatch):
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

    from app.brokers.paper.broker import PaperBroker
    monkeypatch.setattr(PaperBroker, "quote", fake_quote)


# ---- Analyzer mode ----


def test_analyzer_toggle_endpoint(client, auth_headers):
    r = client.get("/api/v1/analyzer", headers=auth_headers)
    assert r.status_code == 200
    assert "analyzer_mode" in r.json()

    r2 = client.post("/api/v1/analyzer/toggle", json={"enabled": True}, headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["analyzer_mode"] is True

    r3 = client.post("/api/v1/analyzer/toggle", json={"enabled": False}, headers=auth_headers)
    assert r3.status_code == 200
    assert r3.json()["analyzer_mode"] is False


def test_analyzer_compat_and_settings(client, auth_headers):
    r = client.post("/api/analyzer/enable", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["analyzer_mode"] is True

    r2 = client.get("/api/v1/settings/", headers=auth_headers)
    assert r2.status_code == 200
    assert "analyzer_mode" in r2.json()

    r3 = client.patch("/api/v1/settings/", json={"analyzer_mode": False}, headers=auth_headers)
    assert r3.status_code == 200
    assert r3.json()["analyzer_mode"] is False

    client.post("/api/analyzer/disable", headers=auth_headers)


# ---- Smart order ----


def test_smart_order_immediate(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/smart",
        json={"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 10, "chase": True},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "filled"
    assert body["order_ids"] and body["order_ids"][0] is not None


# ---- Basket order ----


def test_basket_order_immediate(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/basket",
        json={"orders": [
            {"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 2},
            {"symbol": "NSE:TCS", "side": "BUY", "quantity": 3},
        ]},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "filled"
    assert len(body["order_ids"]) == 2


# ---- Split order ----


def test_split_order_immediate(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    r = client.post(
        "/api/v1/orders/split",
        json={"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 10, "splits": 3},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "filled"
    assert len(body["order_ids"]) == 3


# ---- Action center integration ----


def test_smart_order_approval_flow(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    # Enable approval mode
    client.patch("/api/v1/settings/", json={"execution_mode": "REQUIRE_APPROVAL"}, headers=auth_headers)
    try:
        r = client.post(
            "/api/v1/orders/smart",
            json={"symbol": "NSE:PHASE4SMART", "side": "BUY", "quantity": 5},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        item_id = r.json()["id"]
        assert r.json()["status"] == "pending_approval"

        # Action center list
        lr = client.get("/api/action-center", headers=auth_headers)
        assert lr.status_code == 200
        assert any(i["id"] == item_id for i in lr.json())

        # Approve + execute
        ar = client.post(f"/api/action-center/{item_id}/approve", headers=auth_headers)
        assert ar.status_code == 200
        er = client.post(f"/api/action-center/{item_id}/execute", headers=auth_headers)
        assert er.status_code == 200, er.text
        assert er.json()["status"] == "executed"
    finally:
        client.patch("/api/v1/settings/", json={"execution_mode": "PAPER"}, headers=auth_headers)


def test_basket_split_approval_execute(client, auth_headers, monkeypatch):
    _mock_quote(monkeypatch)
    client.patch("/api/v1/settings/", json={"execution_mode": "REQUIRE_APPROVAL"}, headers=auth_headers)
    try:
        r1 = client.post(
            "/api/v1/orders/basket",
            json={"orders": [{"symbol": "NSE:PHASE4BASKET", "side": "BUY", "quantity": 2}]},
            headers=auth_headers,
        )
        assert r1.status_code == 201
        iid1 = r1.json()["id"]
        client.post(f"/api/action-center/{iid1}/approve", headers=auth_headers)
        er1 = client.post(f"/api/action-center/{iid1}/execute", headers=auth_headers)
        assert er1.status_code == 200, er1.text

        r2 = client.post(
            "/api/v1/orders/split",
            json={"symbol": "NSE:PHASE4SPLIT", "side": "BUY", "quantity": 4, "splits": 2},
            headers=auth_headers,
        )
        assert r2.status_code == 201
        iid2 = r2.json()["id"]
        client.post(f"/api/action-center/{iid2}/approve", headers=auth_headers)
        er2 = client.post(f"/api/action-center/{iid2}/execute", headers=auth_headers)
        assert er2.status_code == 200, er2.text
    finally:
        client.patch("/api/v1/settings/", json={"execution_mode": "PAPER"}, headers=auth_headers)