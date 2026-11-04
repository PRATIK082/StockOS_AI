"""Tests for P5-b: agent-tool order approval + autopilot execute approval routing."""

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
        json={"email": "agenttools@test.dev", "username": "agenttoolsuser", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post("/api/auth/login", json={"identifier": "agenttoolsuser", "password": "secret123"})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_id(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _isolate_paper_broker_state():
    """Snapshot/restore PaperBroker class-level state around each test.

    ``_order_index`` / ``_position_index`` are class attributes shared
    process-wide (and across users), so a fill here would trip the
    same-symbol+side duplicate guard in unrelated test modules.
    """
    from app.brokers.paper.broker import PaperBroker

    order_index = dict(PaperBroker._order_index)
    position_index = {k: dict(v) for k, v in PaperBroker._position_index.items()}
    pnl = PaperBroker._daily_gross_pnl
    trade_date = PaperBroker._last_trade_date
    try:
        yield
    finally:
        PaperBroker._order_index.clear()
        PaperBroker._order_index.update(order_index)
        PaperBroker._position_index.clear()
        PaperBroker._position_index.update(position_index)
        PaperBroker._daily_gross_pnl = pnl
        PaperBroker._last_trade_date = trade_date


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


def _set_mode(client, auth_headers, mode: str):
    r = client.patch("/api/v1/settings/", json={"execution_mode": mode}, headers=auth_headers)
    assert r.status_code == 200, r.text


async def _order_count(user_id: str) -> int:
    from sqlalchemy import func, select

    from app.db.models import Order as OrderModel
    from app.db.session import SessionFactory

    async with SessionFactory() as session:
        return await session.scalar(
            select(func.count()).select_from(OrderModel).where(OrderModel.user_id == user_id)
        ) or 0


def test_tool_registry_lists_preview_and_place():
    from app.services.agents.tools import is_order_tool, list_tools

    tools = {t["name"]: t for t in list_tools()}
    assert {"preview_order", "place_order"} <= set(tools)
    assert tools["preview_order"]["side_effects"] is False
    assert tools["place_order"]["side_effects"] is True
    assert is_order_tool("place_order") and not is_order_tool("preview_order")


def test_unknown_tool_rejected():
    import asyncio

    from app.services.agents.tools import AgentToolError, run_tool

    with pytest.raises(AgentToolError):
        asyncio.run(run_tool("blow_up_account", {}, user_id="nobody"))


def test_preview_tool_is_readonly(client, auth_headers, user_id, monkeypatch):
    import asyncio

    _mock_quote(monkeypatch)
    _set_mode(client, auth_headers, "PAPER")
    try:
        from app.services.agents.tools import run_tool

        before = asyncio.run(_order_count(user_id))
        out = asyncio.run(
            run_tool("preview_order", {"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 1}, user_id=user_id)
        )
        assert out["status"] == "preview"
        assert out["price"] == 1500.0
        assert asyncio.run(_order_count(user_id)) == before
    finally:
        _set_mode(client, auth_headers, "PAPER")


def test_place_order_tool_queues_approval_no_fill(client, auth_headers, user_id, monkeypatch):
    import asyncio

    _mock_quote(monkeypatch)
    _set_mode(client, auth_headers, "REQUIRE_APPROVAL")
    try:
        from app.services.agents.tools import run_tool

        before = asyncio.run(_order_count(user_id))
        out = asyncio.run(
            run_tool("place_order", {"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 1}, user_id=user_id)
        )
        assert out["status"] == "pending_approval"
        assert out["id"]
        # No broker fill: no Order row created.
        assert asyncio.run(_order_count(user_id)) == before
        # And the item is visible in the Action Center queue.
        q = client.get("/api/action-center", params={"status_filter": "pending"}, headers=auth_headers)
        assert q.status_code == 200, q.text
        assert any(i["id"] == out["id"] and i["symbol"] == "NSE:RELIANCE" for i in q.json())
    finally:
        _set_mode(client, auth_headers, "PAPER")


def test_place_order_tool_direct_paper_fills(client, auth_headers, user_id, monkeypatch):
    import asyncio

    _mock_quote(monkeypatch)
    _set_mode(client, auth_headers, "PAPER")
    try:
        from app.services.agents.tools import run_tool

        before = asyncio.run(_order_count(user_id))
        out = asyncio.run(
            run_tool("place_order", {"symbol": "NSE:RELIANCE", "side": "BUY", "quantity": 1}, user_id=user_id)
        )
        assert out["status"] == "filled"
        assert out["order_id"]
        assert asyncio.run(_order_count(user_id)) == before + 1
    finally:
        _set_mode(client, auth_headers, "PAPER")


def test_execute_agent_respects_approval_mode(client, auth_headers, user_id, monkeypatch):
    import asyncio

    _mock_quote(monkeypatch)

    async def _no_fill(self, **kwargs):
        raise AssertionError("broker.place_order must not be called in REQUIRE_APPROVAL mode")

    from app.brokers.paper.broker import PaperBroker
    monkeypatch.setattr(PaperBroker, "place_order", _no_fill)

    _set_mode(client, auth_headers, "REQUIRE_APPROVAL")
    try:
        from app.services.autopilot.agents import execute_agent

        before = asyncio.run(_order_count(user_id))
        out = asyncio.run(
            execute_agent(
                user_id,
                [{"symbol": "NSE:RELIANCE", "side": "BUY", "action": "entry",
                  "qty": 1, "allowed": True, "reason": "p5b test"}],
            )
        )
        assert out["fills"] == []
        assert len(out["pending"]) == 1
        assert out["pending"][0]["status"] == "pending_approval"
        assert asyncio.run(_order_count(user_id)) == before
    finally:
        _set_mode(client, auth_headers, "PAPER")
