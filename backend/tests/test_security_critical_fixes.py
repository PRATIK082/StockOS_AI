"""Regression tests for the F-10 security-review critical fixes.

1. ``PATCH`` / ``GET /api/v1/settings/`` require an authenticated user
   (previously open to the network - anyone could flip ``LIVE_ENABLED``).
2. ``POST /api/mcp/clients/stdio`` is admin-only (previously any
   authenticated user could spawn arbitrary server-side commands).
"""

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
        json={"email": "secfix@t.dev", "username": "secfixuser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _promote_to_admin(email: str) -> None:
    import asyncio

    from sqlalchemy import select, update

    from app.db.models.user import User
    from app.db.session import SessionFactory

    async def _promote() -> None:
        async with SessionFactory() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one()
            user.role = "admin"
            await session.execute(update(User).where(User.id == user.id).values(role="admin"))
            await session.commit()

    asyncio.run(_promote())


# ------------------------------------------------------------------------- #
# Settings endpoints require authentication
# ------------------------------------------------------------------------- #


def test_settings_get_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/settings/").status_code == 401


def test_settings_patch_requires_auth(client: TestClient) -> None:
    assert client.patch("/api/v1/settings/", json={"execution_mode": "PAPER"}).status_code == 401


def test_settings_get_and_patch_with_auth(client: TestClient, auth: dict) -> None:
    assert client.get("/api/v1/settings/", headers=auth).status_code == 200
    try:
        r = client.patch(
            "/api/v1/settings/", json={"execution_mode": "REQUIRE_APPROVAL"}, headers=auth
        )
        assert r.status_code == 200, r.text
        assert r.json()["execution_mode"] == "REQUIRE_APPROVAL"
    finally:
        r = client.patch("/api/v1/settings/", json={"execution_mode": "PAPER"}, headers=auth)
        assert r.status_code == 200, r.text


# ------------------------------------------------------------------------- #
# MCP stdio connect is admin-only
# ------------------------------------------------------------------------- #


def _stdio_body() -> dict:
    return {"name": "evil", "command": ["definitely-not-a-real-binary-xyz"]}


def test_mcp_stdio_requires_auth(client: TestClient) -> None:
    assert client.post("/api/mcp/clients/stdio", json=_stdio_body()).status_code in (401, 403)


def test_mcp_stdio_forbidden_for_non_admin(client: TestClient, auth: dict) -> None:
    # Fresh registered user is role "user" -> must be rejected BEFORE any
    # process is spawned.
    r = client.post("/api/mcp/clients/stdio", json=_stdio_body(), headers=auth)
    assert r.status_code == 403, r.text


def test_mcp_stdio_admin_passes_guard(client: TestClient, auth: dict) -> None:
    # Admin gets past the RBAC guard; the bogus binary then fails inside the
    # service layer -> 502 proves the guard passed without executing anything.
    _promote_to_admin("secfix@t.dev")
    r = client.post("/api/mcp/clients/stdio", json=_stdio_body(), headers=auth)
    assert r.status_code == 502, r.text
