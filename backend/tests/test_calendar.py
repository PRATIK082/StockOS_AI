"""Tests for Phase 9d: market calendar seed + admin overlay + status."""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
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
        json={"email": "cal@t.dev", "username": "caluser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_seed_holidays_present(client: TestClient, auth: dict) -> None:
    body = client.get("/api/calendar/holidays?year=2025", headers=auth).json()
    assert body["year"] == 2025
    by_date = {h["date"]: h for h in body["holidays"]}
    assert by_date["2025-12-25"]["name"] == "Christmas"
    assert by_date["2025-12-25"]["source"] == "seed"
    dates = [h["date"] for h in body["holidays"]]
    assert dates == sorted(dates)


def test_seed_loads_from_file() -> None:
    from app.services.market_calendar import load_seed_holidays

    seed = load_seed_holidays()
    assert any(r["date"] == "2025-12-25" for r in seed)
    assert all(len(r["date"]) == 10 for r in seed)


def test_trading_day_logic() -> None:
    from app.services.market_calendar import is_trading_day, next_trading_day

    assert not is_trading_day(date(2026, 11, 1), {})  # Sunday
    assert not is_trading_day(date(2025, 12, 25), {"2025-12-25"})
    assert is_trading_day(date(2025, 12, 24), {"2025-12-25"})  # Wednesday
    # Friday 2025-12-26 -> next trading day skips weekend, lands Monday 29th.
    assert next_trading_day(date(2025, 12, 26), {"2025-12-25"}) == date(2025, 12, 29)


def test_status_holiday_and_open() -> None:
    from app.services.market_calendar import get_status

    # 2025-12-25 04:00 UTC = 09:30 IST, inside market hours but a holiday.
    closed = get_status(datetime(2025, 12, 25, 4, 0), {"2025-12-25": "Christmas"})
    assert closed["is_open"] is False
    assert closed["reason"] == "holiday"
    assert closed["holiday"] == "Christmas"
    # Wednesday 2025-12-24 05:00 UTC = 10:30 IST -> open session.
    open_ = get_status(datetime(2025, 12, 24, 5, 0), {})
    assert open_["is_open"] is True
    assert open_["reason"] == "session"
    assert open_["session"]
    # Sunday -> weekend closed.
    weekend = get_status(datetime(2026, 11, 1, 5, 0), {})
    assert weekend["is_open"] is False
    assert weekend["reason"] == "weekend"


def test_timings_shape(client: TestClient, auth: dict) -> None:
    body = client.get("/api/calendar/timings", headers=auth).json()
    assert body["market_open"] == "09:15"
    assert body["market_close"] == "15:30"
    assert "IST" in body["timezone"]


def test_status_endpoint(client: TestClient, auth: dict) -> None:
    body = client.get("/api/calendar/status", headers=auth).json()
    assert "is_open" in body and "reason" in body
    assert body["reason"] in ("weekend", "holiday", "session")
    assert body.get("next_trading_day")  # always computable


def test_admin_crud_and_nonadmin_forbidden(client: TestClient, auth: dict) -> None:
    # Fresh registered user is role "user" -> admin routes forbidden.
    assert client.post("/api/calendar/holidays",
                       json={"date": "2026-01-02", "name": "X"},
                       headers=auth).status_code == 403

    # Promote to admin directly in the DB, then CRUD works.
    import asyncio

    from sqlalchemy import select, update

    from app.db.models.user import User
    from app.db.session import SessionFactory

    async def _promote() -> None:
        async with SessionFactory() as session:
            user = (await session.execute(select(User).where(User.email == "cal@t.dev"))).scalar_one()
            user.role = "admin"
            await session.execute(update(User).where(User.id == user.id).values(role="admin"))
            await session.commit()

    asyncio.run(_promote())
    assert client.post("/api/calendar/holidays",
                       json={"date": "2026-01-02", "name": "Test Holiday"},
                       headers=auth).status_code == 201
    body = client.get("/api/calendar/holidays?year=2026", headers=auth).json()
    by_date = {h["date"]: h for h in body["holidays"]}
    assert by_date["2026-01-02"]["source"] == "admin"

    # Override a seed date, verify, then delete (tombstone hides the seed).
    assert client.post("/api/calendar/holidays",
                       json={"date": "2025-12-25", "name": "Xmas (renamed)"},
                       headers=auth).status_code == 201
    body = client.get("/api/calendar/holidays?year=2025", headers=auth).json()
    assert {h["date"]: h for h in body["holidays"]}["2025-12-25"]["name"] == "Xmas (renamed)"
    assert client.delete("/api/calendar/holidays/2025-12-25", headers=auth).status_code == 200
    body = client.get("/api/calendar/holidays?year=2025", headers=auth).json()
    assert "2025-12-25" not in {h["date"] for h in body["holidays"]}

    # Deleting an unknown non-seed date is 404.
    assert client.delete("/api/calendar/holidays/2030-06-15", headers=auth).status_code == 404
