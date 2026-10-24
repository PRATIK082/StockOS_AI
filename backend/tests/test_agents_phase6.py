"""Tests for Phase 6: agent memory store, grounding gate, swarm presets."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

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
    token = client.post(
        "/api/auth/register",
        json={"email": "mem@t.dev", "username": "memoryuser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_memory_store_crud(client: TestClient) -> None:
    import asyncio

    from app.services.memory.store import memory_store

    async def _run() -> None:
        await memory_store.set("u1", "insight:NSE:RELIANCE", {"trend": "up", "score": 0.8}, kind="insight", scope="NSE:RELIANCE")
        got = await memory_store.get("u1", "insight:NSE:RELIANCE")
        assert got["kind"] == "insight" and got["value"]["trend"] == "up"
        await memory_store.set("u1", "insight:NSE:RELIANCE", {"trend": "sideways"}, kind="insight", scope="NSE:RELIANCE")
        got2 = await memory_store.get("u1", "insight:NSE:RELIANCE")
        assert got2["value"]["trend"] == "sideways"
        await memory_store.set("u1", "note:abc", "hello", kind="note", scope="")
        listed = await memory_store.list("u1", kind="insight")
        assert len(listed) == 1
        assert await memory_store.delete("u1", "note:abc") is True
        assert await memory_store.delete("u1", "note:abc") is False
        assert await memory_store.get("u2", "insight:NSE:RELIANCE") is None

    asyncio.run(_run())


def test_memory_endpoint(client: TestClient, auth: dict) -> None:
    r = client.post("/api/memory", headers=auth, json={"key": "note:test", "value": {"x": 1}, "kind": "note", "scope": ""})
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True
    r2 = client.get("/api/memory", headers=auth)
    assert r2.status_code == 200
    assert any(m["key"] == "note:test" for m in r2.json())
    r3 = client.delete("/api/memory/note:test", headers=auth)
    assert r3.status_code == 200


def test_grounding_gate() -> None:
    from app.services.agents.grounding import grounding_gate

    facts = [
        {"label": "close", "value": 2473.4, "symbol": "NSE:RELIANCE"},
        {"label": "rsi", "value": 55.2, "symbol": "NSE:RELIANCE"},
    ]
    good = "Reliance closed at 2473.4. The RSI is 55.2. It looks well supported."
    r = grounding_gate.verify(good, facts)
    assert r["supported"] == 2 and r["contradicted"] == 0 and r["passed"] is True

    bad = "Reliance closed at 1000.0. The RSI is 90."
    r2 = grounding_gate.verify(bad, facts)
    assert r2["contradicted"] == 2 and r2["passed"] is False

    vague = "The stock looks strong heading into the weekend."
    r3 = grounding_gate.verify(vague, facts)
    assert r3["supported"] == 0 and r3["unverifiable"] >= 1 and r3["passed"] is False


def test_swarm_presets() -> None:
    from app.services.agents.swarm_presets import build_dag, list_presets

    presets = list_presets()
    assert len(presets) == 30
    dag = build_dag("quant-sweep")
    roles = {n["role"] for n in dag["nodes"]}
    assert {"screen", "verify", "analyze", "decide"} <= roles
    deps = {n["role"]: n["depends_on"] for n in dag["nodes"]}
    assert deps["verify"] == ["screen"]
    assert build_dag("nope")["error"]
