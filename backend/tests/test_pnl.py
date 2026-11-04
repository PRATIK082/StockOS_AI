"""Tests for Phase 9b: FIFO realized PnL + summary/equity routes."""

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
        json={"email": "pnl@t.dev", "username": "pnluser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_id(client: TestClient, auth: dict) -> str:
    return client.get("/api/auth/me", headers=auth).json()["id"]


def _seed_fills(user_id: str) -> None:
    import asyncio

    from app.db.models.order import Order
    from app.db.session import SessionFactory

    async def _go() -> None:
        async with SessionFactory() as session:
            session.add_all(
                [
                    Order(user_id=user_id, symbol="NSE:RELIANCE", side="BUY",
                          quantity="10", price=100.0, status="filled", order_type="MARKET"),
                    Order(user_id=user_id, symbol="NSE:RELIANCE", side="SELL",
                          quantity="6", price=110.0, status="filled", order_type="MARKET"),
                    Order(user_id=user_id, symbol="NSE:RELIANCE", side="SELL",
                          quantity="4", price=90.0, status="filled", order_type="MARKET"),
                    Order(user_id=user_id, symbol="NSE:TCS", side="BUY",
                          quantity="5", price=50.0, status="pending", order_type="MARKET"),
                ]
            )
            await session.commit()

    asyncio.run(_go())


def test_fifo_unit() -> None:
    from app.services.pnl import fifo_realized

    out = fifo_realized(
        [
            {"symbol": "X", "side": "BUY", "quantity": "10", "price": 100.0},
            {"symbol": "X", "side": "SELL", "quantity": "6", "price": 110.0},
            {"symbol": "X", "side": "SELL", "quantity": "4", "price": 90.0},
        ]
    )
    assert out["total"] == pytest.approx(20.0)  # 6*10 - 4*10
    assert out["wins"] == 1 and out["losses"] == 1 and out["sells"] == 2
    assert out["per_symbol"] == {"X": pytest.approx(20.0)}


def test_fifo_ignores_unmatched_shorts() -> None:
    from app.services.pnl import fifo_realized

    out = fifo_realized([{"symbol": "Y", "side": "SELL", "quantity": "3", "price": 10.0}])
    assert out["total"] == pytest.approx(0.0)
    assert out["flats"] == 1  # no cost basis: contributes nothing, counted flat


def test_summary_realized(client: TestClient, auth: dict, user_id: str) -> None:
    _seed_fills(user_id)
    body = client.get("/api/pnl/summary?range=all", headers=auth).json()
    assert body["fills"] == 3  # pending order excluded
    assert body["realized"]["total"] == pytest.approx(20.0)
    assert body["realized"]["wins"] == 1
    assert body["realized"]["losses"] == 1
    assert body["unrealized"]["total"] == pytest.approx(0.0)  # no holdings
    assert body["total_pnl"] == pytest.approx(20.0)


def test_equity_curve_shape(client: TestClient, auth: dict) -> None:
    body = client.get("/api/pnl/equity?range=all", headers=auth).json()
    points = body["points"]
    assert len(points) == 3  # two sell steps + live point
    assert points[0]["realized"] == pytest.approx(60.0)
    assert points[1]["realized"] == pytest.approx(20.0)
    assert points[-1]["live"] is True
    assert points[-1]["total"] == pytest.approx(20.0)
    assert "note" in body


def test_range_validation(client: TestClient, auth: dict) -> None:
    assert client.get("/api/pnl/summary?range=bogus", headers=auth).status_code == 422
    assert client.get("/api/pnl/summary", headers=auth).status_code == 200
