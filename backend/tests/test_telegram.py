"""Tests for Phase 9c: Telegram read-only bot (no network; fake updates)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _tables() -> None:
    import asyncio

    from app.db.base import Base
    from app.db.session import engine

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client: TestClient) -> dict:
    token = client.post(
        "/api/auth/register",
        json={"email": "tg@t.dev", "username": "tguser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _promote() -> None:
    import asyncio

    from sqlalchemy import select, update

    from app.db.models.user import User
    from app.db.session import SessionFactory

    async def _go() -> None:
        async with SessionFactory() as session:
            user = (await session.execute(select(User).where(User.email == "tg@t.dev"))).scalar_one()
            await session.execute(update(User).where(User.id == user.id).values(role="admin"))
            await session.commit()

    asyncio.run(_go())


class FakeMsg:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.sent.append(text)


def _update(chat_id: int) -> tuple[SimpleNamespace, FakeMsg]:
    msg = FakeMsg()
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), message=msg), msg


def _context() -> SimpleNamespace:
    return SimpleNamespace(application=SimpleNamespace(bot_data={"owner_user_id": None}))


async def test_emit_noop_when_unconfigured() -> None:
    from app.services.telegram import alerts

    assert await alerts.emit("order_executed", "BUY 1 X") is False


async def test_guard_refuses_non_allowlisted_chat(monkeypatch) -> None:
    from app.services.telegram import bot as tg_bot

    monkeypatch.setattr(tg_bot, "_CHAT_IDS", [111])
    update, msg = _update(999)
    await tg_bot.status_cmd(update, _context())
    assert msg.sent == ["Not authorized for this bot."]


async def test_status_cmd_replies_for_allowlisted_chat(monkeypatch) -> None:
    from app.services.telegram import bot as tg_bot

    monkeypatch.setattr(tg_bot, "_CHAT_IDS", [111])
    update, msg = _update(111)
    await tg_bot.status_cmd(update, _context())
    assert len(msg.sent) == 1
    assert "Market:" in msg.sent[0] and "Mode:" in msg.sent[0]


async def test_builders_without_owner() -> None:
    from app.services.telegram import bot as tg_bot

    assert await tg_bot.build_positions_text(None) == "Bot owner not linked."
    assert await tg_bot.build_pnl_text(None) == "Bot owner not linked."


def test_status_shape_and_nonadmin_forbidden(client: TestClient, auth: dict) -> None:
    body = client.get("/api/telegram/status", headers=auth).json()
    assert body == {"configured": False, "enabled": False, "running": False,
                    "chat_ids": [], "owner_linked": False}
    assert "token" not in json.dumps(body).lower().replace("owner_linked", "")
    assert client.put("/api/telegram/config", json={"enabled": True}, headers=auth).status_code == 403
    assert client.post("/api/telegram/test", headers=auth).status_code == 403


def test_token_write_only_and_test_needs_running(client: TestClient, auth: dict) -> None:
    _promote()
    secret = "SECRET-TOKEN-12345"
    body = client.put("/api/telegram/config",
                      json={"token": secret, "chat_ids": [111], "enabled": True},
                      headers=auth).json()
    assert secret not in json.dumps(body)
    assert body["configured"] is True and body["chat_ids"] == [111]
    assert body["running"] is False  # fake token: start fails safely, never raises

    status = client.get("/api/telegram/status", headers=auth).json()
    assert secret not in json.dumps(status)
    assert status["configured"] is True and status["owner_linked"] is True

    # Bot not running (bad token) -> test message is 409, not a crash.
    assert client.post("/api/telegram/test", headers=auth).status_code == 409
    assert client.post("/api/telegram/restart", headers=auth).json()["running"] is False
