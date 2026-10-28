"""Tests for Phase 1 remaining security features: CSRF, IP ban, token revocation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TMPDIR = tempfile.mkdtemp(prefix="smtest_sec_")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}")
os.environ.setdefault("STOCKOS_RATE_LIMIT_DEFAULT_PER_MINUTE", "100000")
os.environ.setdefault("STOCKOS_RATE_LIMIT_AUTH_PER_MINUTE", "100000")

from app.main import app  # noqa: E402


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


def _register(client: TestClient, username: str) -> str:
    try:
        client.cookies.clear()
    except Exception:
        pass
    r = client.post(
        "/api/auth/register",
        json={"email": f"{username}@t.dev", "username": username, "password": "secret123"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def test_csrf_token_endpoint_sets_cookie(client: TestClient) -> None:
    r = client.get("/api/auth/csrf-token")
    assert r.status_code == 200
    body = r.json()
    assert "csrf_token" in body
    token = body["csrf_token"]
    assert token
    # cookie set
    assert "csrf_token" in client.cookies or "csrftoken" in client.cookies


def test_csrf_blocks_state_change_without_header(client: TestClient) -> None:
    # obtain csrf cookie
    r = client.get("/api/auth/csrf-token")
    token = r.json()["csrf_token"]
    # state-changing request with cookie but no header -> 403
    r2 = client.post(
        "/api/auth/register",
        json={"email": "csrf1@t.dev", "username": "csrfuser1", "password": "secret123"},
        cookies={"csrf_token": token},
    )
    assert r2.status_code == 403

    # with matching header -> not blocked by CSRF (may succeed)
    r3 = client.post(
        "/api/auth/register",
        json={"email": "csrf2@t.dev", "username": "csrfuser2", "password": "secret123"},
        cookies={"csrf_token": token},
        headers={"X-CSRF-Token": token},
    )
    assert r3.status_code != 403


def test_ip_ban_after_threshold(client: TestClient) -> None:
    try:
        client.cookies.clear()
    except Exception:
        pass
    ident = "banvictim"
    for _ in range(5):
        r = client.post("/api/auth/login", json={"identifier": ident, "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"identifier": ident, "password": "wrong"})
    assert r.status_code in (429, 403)


def test_token_has_jti(client: TestClient) -> None:
    try:
        client.cookies.clear()
    except Exception:
        pass
    from jose import jwt
    from app.core.config import settings

    token = _register(client, "jtiuser")
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert "jti" in payload


def test_logout_revokes_token(client: TestClient) -> None:
    try:
        client.cookies.clear()
    except Exception:
        pass
    token = _register(client, "logoutuser")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    r = client.post("/api/auth/logout", headers=headers)
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_revoked_token_rejected(client: TestClient) -> None:
    from app.core.security import revoke_token, create_access_token

    token = create_access_token("fakeuser", "user")
    from jose import jwt
    from app.core.config import settings

    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    revoke_token(payload["jti"], payload.get("exp"))
    # get_current_user path requires user in DB; token with unknown sub -> 401 anyway.
    # Ensure blacklist reports revoked.
    from app.core.security import is_token_revoked

    assert is_token_revoked(payload["jti"]) is True
