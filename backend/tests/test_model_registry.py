"""Tests for model registry UI data endpoints."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402


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
        json={"email": "mr@t.dev", "username": "modeluser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_llm_registry_endpoint(client: TestClient) -> None:
    r = client.get("/api/llm/registry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "providers" in body
    assert isinstance(body["providers"], list)
    assert len(body["providers"]) > 0
    for p in body["providers"]:
        assert "provider" in p
        assert "models" in p


def test_trading_model_registry_endpoint(client: TestClient, auth: dict) -> None:
    r = client.get("/api/trading/model-registry", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "providers" in body
    assert len(body["providers"]) > 0
    for p in body["providers"]:
        assert "provider" in p
        assert "models" in p
        assert "label" in p


def test_trading_providers_still_works(client: TestClient, auth: dict) -> None:
    r = client.get("/api/trading/providers", headers=auth)
    assert r.status_code == 200, r.text
    assert "providers" in r.json()
