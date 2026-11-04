"""Tests for Phase 9e: broker diagnostics + auth verify + TOTP seed."""

from __future__ import annotations

import json
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
        json={"email": "diag@t.dev", "username": "diaguser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _promote() -> None:
    import asyncio

    from sqlalchemy import select, update

    from app.db.models.user import User
    from app.db.session import SessionFactory

    async def _go() -> None:
        async with SessionFactory() as session:
            user = (await session.execute(select(User).where(User.email == "diag@t.dev"))).scalar_one()
            await session.execute(update(User).where(User.id == user.id).values(role="admin"))
            await session.commit()

    asyncio.run(_go())


def test_diagnostics_shape_no_secrets(client: TestClient, auth: dict) -> None:
    body = client.get("/api/brokers/diagnostics", headers=auth).json()
    names = {b["name"] for b in body["brokers"]}
    assert {"paper", "zerodha", "angelone"} <= names
    paper = next(b for b in body["brokers"] if b["name"] == "paper")
    assert paper["plugin_present"] is True
    assert paper["class_loadable"] is True
    assert paper["credentials_stored"] is False
    assert paper["totp_configured"] is False
    assert paper["last_auth"] is None
    assert isinstance(paper["capabilities"], list) and paper["capabilities"]
    for entry in body["brokers"]:
        assert "api_key" not in json.dumps(entry).lower().replace("credentials_stored", "")


def test_totp_seed_admin_only_and_validated(client: TestClient, auth: dict) -> None:
    seed = "JBSWY3DPEHPK3PXP"  # valid base32
    assert client.put("/api/brokers/paper/totp-seed", json={"seed": seed},
                      headers=auth).status_code == 403
    _promote()
    assert client.put("/api/brokers/paper/totp-seed", json={"seed": "!!!not-base32!!!"},
                      headers=auth).status_code == 422
    body = client.put("/api/brokers/paper/totp-seed", json={"seed": seed},
                      headers=auth).json()
    assert body == {"name": "paper", "totp_configured": True}
    assert seed not in json.dumps(body)
    diag = client.get("/api/brokers/diagnostics", headers=auth).json()
    paper = next(b for b in diag["brokers"] if b["name"] == "paper")
    assert paper["totp_configured"] is True
    assert seed not in json.dumps(diag)


def test_credentials_write_only_and_paper_verify(client: TestClient, auth: dict) -> None:
    body = client.post("/api/brokers/paper/credentials",
                       json={"api_key": "KEY-ABC-123", "api_secret": "SECRET-XYZ-999"},
                       headers=auth).json()
    assert body == {"name": "paper", "credentials_stored": True}
    assert "KEY-ABC-123" not in json.dumps(body) and "SECRET-XYZ-999" not in json.dumps(body)

    verify = client.post("/api/brokers/paper/auth/verify", headers=auth).json()
    assert verify["name"] == "paper"
    assert verify["authenticated"] is True
    assert "last_auth_at" in verify
    assert "access_token" not in json.dumps(verify).lower()

    diag = client.get("/api/brokers/diagnostics", headers=auth).json()
    paper = next(b for b in diag["brokers"] if b["name"] == "paper")
    assert paper["credentials_stored"] is True
    assert paper["last_auth"]["ok"] is True
    assert "KEY-ABC-123" not in json.dumps(diag) and "SECRET-XYZ-999" not in json.dumps(diag)


def test_unknown_broker_and_missing_creds(client: TestClient, auth: dict) -> None:
    assert client.post("/api/brokers/nope/auth/verify", headers=auth).status_code == 404
    assert client.put("/api/brokers/nope/totp-seed", json={"seed": "JBSWY3DPEHPK3PXP"},
                      headers=auth).status_code == 404
    # Auth-required broker without stored credentials -> 409, not a crash.
    r = client.post("/api/brokers/zerodha/auth/verify", headers=auth)
    assert r.status_code == 409
