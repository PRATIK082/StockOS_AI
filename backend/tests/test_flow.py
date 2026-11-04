"""Tests for Phase 7: Flow Visual Strategy Builder.

Covers the pure validator (cycle, dangling edge, unknown type, order missing
params), CRUD round-trip, dry-run with mocked market data, semi-auto live
orders (Action Center pending item + zero fills), and import/export.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="smtest_flow_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

import app.db.models.flow_graph  # noqa: F401  (registers the flow_graphs table)
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
    r = client.post(
        "/api/auth/register",
        json={"email": "flow@t.dev", "username": "flowuser", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "flowuser", "password": "secret123"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_id(client: TestClient, auth: dict) -> str:
    r = client.get("/api/auth/me", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _isolate_paper_broker_state():
    """Snapshot/restore PaperBroker class-level state around each test.

    ``_order_index`` / ``_position_index`` / ``_daily_gross_pnl`` are class
    attributes shared process-wide, so a fill here would trip the
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


def _set_mode(client: TestClient, auth: dict, mode: str) -> None:
    r = client.patch("/api/v1/settings/", json={"execution_mode": mode}, headers=auth)
    assert r.status_code == 200, r.text


def _rising_candles(n: int = 60) -> list[dict]:
    candles = []
    for i in range(n):
        c = 100.0 + i * 1.5
        candles.append({
            "ts": f"2026-01-{1 + i % 28:02d} 09:30",
            "open": c, "high": c * 1.01, "low": c * 0.99,
            "close": c, "volume": 100000,
        })
    return candles


def _mock_history(monkeypatch, candles: list[dict] | None = None):
    from app.services.data.service import MarketDataService

    data = candles if candles is not None else _rising_candles()

    async def fake_history(self, symbol, *args, **kwargs):
        return {"symbol": symbol, "interval": "1d", "candles": [dict(c) for c in data]}

    # NOTE: patch the CLASS, never the market_data singleton instance — an
    # instance-level patch leaves a permanent __dict__ shadow after teardown.
    monkeypatch.setattr(MarketDataService, "get_history_auto", fake_history)


def _chain_graph(symbol: str = "NSE:XYZ") -> dict:
    return {
        "nodes": [
            {"id": "md1", "type": "market_data", "params": {"symbol": symbol}},
            {"id": "ind1", "type": "indicator", "params": {"function": "sma", "period": 5, "input": "md1"}},
            {"id": "cond1", "type": "condition", "params": {"operator": "gt", "left": {"node": "ind1"}, "right": {"value": 0}}},
            {"id": "ord1", "type": "order", "params": {"symbol": symbol, "side": "BUY", "quantity": 1}},
            {"id": "note1", "type": "notification", "params": {"message": "flow test"}},
        ],
        "edges": [
            {"from": "md1", "to": "ind1"},
            {"from": "ind1", "to": "cond1"},
            {"from": "cond1", "to": "ord1"},
            {"from": "ord1", "to": "note1"},
        ],
    }


async def _count_orders(user_id: str) -> int:
    from sqlalchemy import func, select

    from app.db.models.order import Order as OrderModel
    from app.db.session import SessionFactory

    async with SessionFactory() as session:
        return await session.scalar(
            select(func.count()).select_from(OrderModel).where(OrderModel.user_id == user_id)
        ) or 0


async def _count_pending_approvals(user_id: str) -> int:
    from sqlalchemy import func, select

    from app.db.models.action_center import ActionCenterItem
    from app.db.session import SessionFactory

    async with SessionFactory() as session:
        return await session.scalar(
            select(func.count()).select_from(ActionCenterItem).where(
                ActionCenterItem.user_id == user_id, ActionCenterItem.status == "pending"
            )
        ) or 0


# ------------------------------------------------------------------------- #
# Validator unit tests (pure, no I/O)
# ------------------------------------------------------------------------- #

def test_validator_cycle() -> None:
    from app.services.flow.schemas import FlowGraph
    from app.services.flow.validator import validate

    graph = FlowGraph.model_validate({
        "nodes": [
            {"id": "a", "type": "market_data", "params": {"symbol": "X"}},
            {"id": "b", "type": "notification", "params": {}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    })
    codes = [f.code for f in validate(graph)]
    assert "cycle" in codes


def test_validator_dangling_edge() -> None:
    from app.services.flow.schemas import FlowGraph
    from app.services.flow.validator import validate

    graph = FlowGraph.model_validate({
        "nodes": [{"id": "a", "type": "market_data", "params": {"symbol": "X"}}],
        "edges": [{"from": "a", "to": "ghost"}],
    })
    findings = validate(graph)
    assert any(f.code == "dangling_edge" for f in findings)


def test_validator_unknown_type() -> None:
    from app.services.flow.schemas import FlowGraph
    from app.services.flow.validator import validate

    graph = FlowGraph.model_validate({
        "nodes": [{"id": "a", "type": "teleport", "params": {}}],
        "edges": [],
    })
    findings = validate(graph)
    assert any(f.code == "unknown_type" and f.node_id == "a" for f in findings)


def test_validator_order_missing_params() -> None:
    from app.services.flow.schemas import FlowGraph
    from app.services.flow.validator import validate

    graph = FlowGraph.model_validate({
        "nodes": [{"id": "o", "type": "order", "params": {}}],
        "edges": [],
    })
    codes = [f.code for f in validate(graph) if f.node_id == "o"]
    assert codes.count("missing_param") == 3  # symbol, side, quantity


def test_validator_live_order_requires_approval_flag() -> None:
    from app.services.flow.schemas import FlowGraph
    from app.services.flow.validator import validate

    unsafe = FlowGraph.model_validate({
        "nodes": [{"id": "o", "type": "order",
                   "params": {"symbol": "X", "side": "BUY", "quantity": 1, "live": True}}],
        "edges": [],
    })
    assert any(f.code == "approval_unsafe" for f in validate(unsafe))

    safe = FlowGraph.model_validate({
        "nodes": [{"id": "o", "type": "order",
                   "params": {"symbol": "X", "side": "BUY", "quantity": 1,
                              "live": True, "require_approval": True}}],
        "edges": [],
    })
    assert not [f for f in validate(safe) if f.code == "approval_unsafe"]


def test_validator_clean_graph() -> None:
    from app.services.flow.schemas import FlowGraph
    from app.services.flow.validator import validate

    assert validate(FlowGraph.model_validate(_chain_graph())) == []


# ------------------------------------------------------------------------- #
# CRUD round-trip
# ------------------------------------------------------------------------- #

def test_crud_round_trip(client: TestClient, auth: dict) -> None:
    body = {
        "name": "Flow CRUD",
        "graph": _chain_graph(),
        "schedule_cron": "0 9 * * *",
        "enabled": True,
        "paper_only": True,
    }
    r = client.post("/api/flow/graphs", json=body, headers=auth)
    assert r.status_code == 201, r.text
    created = r.json()
    gid = created["id"]
    assert created["name"] == "Flow CRUD"
    assert created["schedule_cron"] == "0 9 * * *"
    assert created["paper_only"] is True

    r = client.get("/api/flow/graphs", headers=auth)
    assert r.status_code == 200, r.text
    assert gid in {g["id"] for g in r.json()}

    r = client.get(f"/api/flow/graphs/{gid}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["definition"]["nodes"][0]["id"] == "md1"

    r = client.patch(f"/api/flow/graphs/{gid}", json={"name": "Renamed", "enabled": False}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed"
    assert r.json()["enabled"] is False

    r = client.delete(f"/api/flow/graphs/{gid}", headers=auth)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/flow/graphs/{gid}", headers=auth).status_code == 404


def test_crud_unknown_type_rejected(client: TestClient, auth: dict) -> None:
    bad = {"name": "Bad", "graph": {"nodes": [{"id": "x", "type": "nope", "params": {}}], "edges": []}}
    assert client.post("/api/flow/graphs", json=bad, headers=auth).status_code == 422
    assert client.post("/api/flow/validate", json={"graph": bad["graph"]}, headers=auth).status_code == 422
    assert client.post("/api/flow/run", json={"inline_graph": bad["graph"], "mode": "dry_run"}, headers=auth).status_code == 422


def test_validate_endpoint_findings(client: TestClient, auth: dict) -> None:
    graph = _chain_graph()
    graph["edges"].append({"from": "md1", "to": "missing"})
    r = client.post("/api/flow/validate", json={"graph": graph}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is False
    assert any(f["code"] == "dangling_edge" for f in body["findings"])

    r = client.post("/api/flow/validate", json={"graph": _chain_graph()}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == {"valid": True, "findings": []}


def test_run_requires_graph_ref(client: TestClient, auth: dict) -> None:
    r = client.post("/api/flow/run", json={"mode": "dry_run"}, headers=auth)
    assert r.status_code == 422
    assert client.get("/api/flow/graphs/does-not-exist", headers=auth).status_code == 404


# ------------------------------------------------------------------------- #
# Dry-run with mocked market data
# ------------------------------------------------------------------------- #

def test_dry_run_mocked_market_data(client: TestClient, auth: dict, user_id: str, monkeypatch) -> None:
    import asyncio

    _mock_history(monkeypatch)
    before = asyncio.run(_count_orders(user_id))
    r = client.post("/api/flow/run", json={"inline_graph": _chain_graph(), "mode": "dry_run"}, headers=auth)
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["mode"] == "dry_run"
    assert report["status"] == "completed"
    by_id = {s["node_id"]: s for s in report["step_results"]}
    assert by_id["md1"]["status"] == "ok"
    assert by_id["md1"]["output"]["bars"] == 60
    assert by_id["ind1"]["status"] == "ok"
    assert by_id["ind1"]["output"]["value"] > 0
    assert by_id["cond1"]["output"] is True
    assert by_id["ord1"]["status"] == "simulated"
    assert by_id["note1"]["status"] == "done"
    # Dry-run never persists fills.
    assert asyncio.run(_count_orders(user_id)) == before


def test_dry_run_missing_data_honest_nulls(client: TestClient, auth: dict, monkeypatch) -> None:
    _mock_history(monkeypatch, candles=[])
    r = client.post("/api/flow/run", json={"inline_graph": _chain_graph("NSE:NODATA")}, headers=auth)
    assert r.status_code == 200, r.text
    report = r.json()
    by_id = {s["node_id"]: s for s in report["step_results"]}
    assert by_id["md1"]["status"] == "empty"
    assert by_id["md1"]["output"] is None
    assert by_id["md1"]["note"]  # honest note, no fabricated data
    assert by_id["ind1"]["output"] is None
    assert by_id["cond1"]["output"] is None


def test_run_stored_graph_id(client: TestClient, auth: dict, monkeypatch) -> None:
    _mock_history(monkeypatch)
    gid = client.post("/api/flow/graphs", json={"name": "Stored run", "graph": _chain_graph()}, headers=auth).json()["id"]
    try:
        r = client.post("/api/flow/run", json={"graph_id": gid, "mode": "dry_run"}, headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"
        assert client.post("/api/flow/run", json={"graph_id": "nope", "mode": "dry_run"}, headers=auth).status_code == 404
    finally:
        client.delete(f"/api/flow/graphs/{gid}", headers=auth)


# ------------------------------------------------------------------------- #
# Semi-auto live order -> Action Center pending item + zero fills
# ------------------------------------------------------------------------- #

def test_live_order_approval_mode_files_action_center(client: TestClient, auth: dict, user_id: str) -> None:
    import asyncio

    graph = {
        "nodes": [{"id": "ord1", "type": "order",
                   "params": {"symbol": "NSE:FLOWAPPROVAL", "side": "BUY", "quantity": 1}}],
        "edges": [],
    }
    _set_mode(client, auth, "REQUIRE_APPROVAL")
    try:
        orders_before = asyncio.run(_count_orders(user_id))
        pending_before = asyncio.run(_count_pending_approvals(user_id))
        r = client.post("/api/flow/run", json={"inline_graph": graph, "mode": "live"}, headers=auth)
        assert r.status_code == 200, r.text
        report = r.json()
        assert report["mode"] == "live"
        step = report["step_results"][0]
        assert step["status"] == "pending_approval"
        assert step["output"]["action_center_id"]
        # Approval item pending, zero fills.
        assert asyncio.run(_count_pending_approvals(user_id)) == pending_before + 1
        assert asyncio.run(_count_orders(user_id)) == orders_before
    finally:
        _set_mode(client, auth, "PAPER")


def test_live_paper_fill_default(client: TestClient, auth: dict, user_id: str) -> None:
    import asyncio

    graph = {
        "nodes": [{"id": "ord1", "type": "order",
                   "params": {"symbol": "NSE:FLOWFILL", "side": "BUY", "quantity": 1}}],
        "edges": [],
    }
    _set_mode(client, auth, "PAPER")
    try:
        orders_before = asyncio.run(_count_orders(user_id))
        r = client.post("/api/flow/run", json={"inline_graph": graph, "mode": "live"}, headers=auth)
        assert r.status_code == 200, r.text
        step = r.json()["step_results"][0]
        assert step["status"] == "filled", step
        assert step["output"]["order_id"]
        assert asyncio.run(_count_orders(user_id)) == orders_before + 1
    finally:
        _set_mode(client, auth, "PAPER")


# ------------------------------------------------------------------------- #
# Import / export round-trip
# ------------------------------------------------------------------------- #

def test_import_export_round_trip(client: TestClient, auth: dict) -> None:
    graph = _chain_graph()
    r = client.post("/api/flow/import", json={"name": "Import me", "graph": graph}, headers=auth)
    assert r.status_code == 201, r.text
    gid = r.json()["id"]

    r = client.get(f"/api/flow/export/{gid}", headers=auth)
    assert r.status_code == 200, r.text
    exported = r.json()
    assert exported["name"] == "Import me"
    assert exported["exported_at"]
    assert exported["definition"]["nodes"] == graph["nodes"]

    # Re-import the exported payload verbatim.
    r = client.post("/api/flow/import", json=exported, headers=auth)
    assert r.status_code == 201, r.text
    gid2 = r.json()["id"]
    assert client.get(f"/api/flow/export/{gid2}", headers=auth).json()["definition"] == exported["definition"]

    client.delete(f"/api/flow/graphs/{gid}", headers=auth)
    client.delete(f"/api/flow/graphs/{gid2}", headers=auth)
