"""Tests for Phase 8: Python Strategy Host.

Covers CRUD round-trip, out-of-process runs (top-level + main(ctx) styles),
honest no-data degradation, timeout kill, user stop, env round-trip
(names-only), log-redaction canary, and approval-mode place_order (pending
Action Center item + zero fills).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="smtest_host_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"
# Deterministic, offline market data for spawned workers (children are
# separate processes, so class-level monkeypatches cannot reach them).
os.environ["STRATEGY_HOST_HISTORY_STUB_JSON"] = json.dumps(
    {"symbol": "STUB", "candles": [], "source": "test-stub"}
)

import app.db.models.strategy_script  # noqa: F401  (registers the strategy_scripts table)
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
        json={"email": "host@t.dev", "username": "hostuser", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "hostuser", "password": "secret123"},
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
    """Snapshot/restore PaperBroker class-level state around each test."""
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


def _make_script(client: TestClient, auth: dict, name: str, code: str) -> str:
    r = client.post(
        "/api/strategy-host/scripts",
        json={"name": name, "code": code, "enabled": True},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wait_for_log_status(
    client: TestClient, auth: dict, script_id: str, want: set[str], deadline_s: float = 60.0
) -> dict:
    end = time.time() + deadline_s
    last: dict = {}
    while time.time() < end:
        r = client.get(
            f"/api/strategy-host/scripts/{script_id}/logs?tail=200", headers=auth
        )
        assert r.status_code == 200, r.text
        last = r.json()
        assert "logs" in last and isinstance(last["logs"], list)
        if last.get("status") in want:
            return last
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {want}; last={json.dumps(last)[:500]}")


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
# CRUD round-trip (+ auth/404 honesty)
# ------------------------------------------------------------------------- #

def test_crud_round_trip(client: TestClient, auth: dict) -> None:
    sid = _make_script(client, auth, "Host CRUD", 'ctx.log("hi")')
    try:
        r = client.get("/api/strategy-host/scripts", headers=auth)
        assert r.status_code == 200, r.text
        assert sid in {s["id"] for s in r.json()}

        r = client.get(f"/api/strategy-host/scripts/{sid}", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["code"] == 'ctx.log("hi")'
        assert r.json()["enabled"] is True

        r = client.patch(
            f"/api/strategy-host/scripts/{sid}",
            json={"name": "Renamed", "enabled": False, "schedule_cron": "0 9 * * *"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Renamed"
        assert body["enabled"] is False
        assert body["schedule_cron"] == "0 9 * * *"

        # Clearing the schedule with explicit null works (fields_set aware).
        r = client.patch(
            f"/api/strategy-host/scripts/{sid}", json={"schedule_cron": None}, headers=auth
        )
        assert r.status_code == 200, r.text
        assert r.json()["schedule_cron"] is None
    finally:
        r = client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)
        assert r.status_code == 200, r.text
        assert client.get(f"/api/strategy-host/scripts/{sid}", headers=auth).status_code == 404


def test_auth_and_404_honesty(client: TestClient, auth: dict) -> None:
    assert client.get("/api/strategy-host/scripts").status_code == 401
    assert client.get("/api/strategy-host/scripts/does-not-exist", headers=auth).status_code == 404
    assert client.post("/api/strategy-host/scripts/does-not-exist/run", headers=auth).status_code == 404
    assert client.get("/api/strategy-host/scripts/does-not-exist/logs", headers=auth).status_code == 404
    assert client.get("/api/strategy-host/scripts/does-not-exist/env", headers=auth).status_code == 404
    assert client.put("/api/strategy-host/scripts/does-not-exist/env", json={"A": "b"}, headers=auth).status_code == 404


# ------------------------------------------------------------------------- #
# Out-of-process runs
# ------------------------------------------------------------------------- #

def test_trivial_run_returns_ctx_log_output(client: TestClient, auth: dict) -> None:
    code = 'ctx.log("top-level-hello")\n\ndef main(ctx):\n    ctx.log("main-hello")\n'
    sid = _make_script(client, auth, "Host trivial", code)
    try:
        r = client.post(f"/api/strategy-host/scripts/{sid}/run", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"] and body["status"] == "running"

        done = _wait_for_log_status(client, auth, sid, {"completed"})
        text = "\n".join(done["logs"])
        assert "top-level-hello" in text
        assert "main-hello" in text
    finally:
        client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)


def test_no_data_script_degrades_honestly(client: TestClient, auth: dict) -> None:
    code = (
        "h = ctx.history('NSE:NODATAHOST', '1d', '1y')\n"
        "ctx.log('bars=%s' % len(h.get('candles', [])))\n"
        "ctx.log('src=%s' % h.get('source'))\n"
    )
    sid = _make_script(client, auth, "Host nodata", code)
    try:
        assert client.post(f"/api/strategy-host/scripts/{sid}/run", headers=auth).status_code == 200
        done = _wait_for_log_status(client, auth, sid, {"completed"})
        text = "\n".join(done["logs"])
        assert "bars=0" in text  # honest empty, never fabricated
        assert "src=test-stub" in text
    finally:
        client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)


def test_infinite_loop_killed_by_timeout(client: TestClient, auth: dict) -> None:
    code = "import time\nwhile True:\n    time.sleep(0.05)\n"
    sid = _make_script(client, auth, "Host looper", code)
    try:
        r = client.post(
            f"/api/strategy-host/scripts/{sid}/run",
            json={"timeout_seconds": 2},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        done = _wait_for_log_status(client, auth, sid, {"killed"})
        assert done["run_id"] == r.json()["run_id"]
    finally:
        client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)


def test_stop_kills_running_script(client: TestClient, auth: dict) -> None:
    code = "import time\nwhile True:\n    time.sleep(0.1)\n"
    sid = _make_script(client, auth, "Host stoppable", code)
    try:
        r = client.post(f"/api/strategy-host/scripts/{sid}/run", headers=auth)
        assert r.status_code == 200, r.text
        # Give the worker a moment to start, then stop it.
        time.sleep(4)
        r = client.post(f"/api/strategy-host/scripts/{sid}/stop", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["stopped"] is True
        assert r.json()["status"] == "stopped"
        done = _wait_for_log_status(client, auth, sid, {"stopped"})
        assert done["run_id"] == r.json()["run_id"]
    finally:
        client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)


# ------------------------------------------------------------------------- #
# Env round-trip + redaction canary
# ------------------------------------------------------------------------- #

def test_env_round_trip_names_only(client: TestClient, auth: dict) -> None:
    sid = _make_script(client, auth, "Host env", 'ctx.log("env test")')
    try:
        secret = "super-secret-value-abc123"
        r = client.put(
            f"/api/strategy-host/scripts/{sid}/env",
            json={"HOST_E2E_KEY": secret},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert "HOST_E2E_KEY" in r.json()["keys"]

        r = client.get(f"/api/strategy-host/scripts/{sid}/env", headers=auth)
        assert r.status_code == 200, r.text
        assert "HOST_E2E_KEY" in r.json()["keys"]
        assert secret not in r.text  # values never readable
    finally:
        client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)


def test_log_redaction_canary(client: TestClient, auth: dict) -> None:
    sid = _make_script(client, auth, "Host canary", "placeholder")
    canary = "host-canary-9f8e7d6c5b4a"
    try:
        assert client.put(
            f"/api/strategy-host/scripts/{sid}/env",
            json={"HOST_CANARY": canary},
            headers=auth,
        ).status_code == 200
        code = (
            "import os\n"
            'ctx.log("leak attempt: " + os.environ.get("HOST_CANARY", "MISSING"))\n'
        )
        assert client.patch(
            f"/api/strategy-host/scripts/{sid}", json={"code": code}, headers=auth
        ).status_code == 200
        assert client.post(f"/api/strategy-host/scripts/{sid}/run", headers=auth).status_code == 200
        done = _wait_for_log_status(client, auth, sid, {"completed"})
        text = "\n".join(done["logs"])
        assert canary not in text  # stored secret value never appears in logs
        assert "***" in text
    finally:
        client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)


def test_env_validation_honest_errors(client: TestClient, auth: dict) -> None:
    sid = _make_script(client, auth, "Host envval", 'ctx.log("x")')
    try:
        assert client.put(
            f"/api/strategy-host/scripts/{sid}/env", json={"bad-key!": "v"}, headers=auth
        ).status_code == 422
        assert client.put(
            f"/api/strategy-host/scripts/{sid}/env", json={"OK_KEY": 123}, headers=auth
        ).status_code == 422
    finally:
        client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)


# ------------------------------------------------------------------------- #
# Approval-mode place_order -> pending item + zero fills
# ------------------------------------------------------------------------- #

def test_approval_mode_place_order(client: TestClient, auth: dict, user_id: str) -> None:
    import asyncio

    code = 'ctx.place_order("NSE:HOSTAPPROVAL", "BUY", 1)\nctx.log("order attempted")\n'
    sid = _make_script(client, auth, "Host approval", code)
    _set_mode(client, auth, "REQUIRE_APPROVAL")
    try:
        orders_before = asyncio.run(_count_orders(user_id))
        pending_before = asyncio.run(_count_pending_approvals(user_id))
        assert client.post(f"/api/strategy-host/scripts/{sid}/run", headers=auth).status_code == 200
        done = _wait_for_log_status(client, auth, sid, {"completed"})
        text = "\n".join(done["logs"])
        assert "pending approval" in text
        assert asyncio.run(_count_pending_approvals(user_id)) == pending_before + 1
        assert asyncio.run(_count_orders(user_id)) == orders_before  # zero fills
    finally:
        _set_mode(client, auth, "PAPER")
        client.delete(f"/api/strategy-host/scripts/{sid}", headers=auth)
