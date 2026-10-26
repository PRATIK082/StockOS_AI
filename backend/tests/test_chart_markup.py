"""Tests for agent -> chart markup integration."""

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
        json={"email": "cm@t.dev", "username": "chartuser", "password": "secret123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _candles(n: int = 80):
    out = []
    price = 100.0
    for i in range(n):
        price += 0.5 if i % 3 else -0.3
        out.append(
            {
                "ts": f"2025-01-{(i % 28) + 1:02d}",
                "open": price - 0.2,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "volume": 1000,
            }
        )
    return out


def test_chart_markup_endpoint(client: TestClient, auth: dict, monkeypatch) -> None:
    async def _auto(symbol, *, interval="1d", period="3mo", provider=None, chain=None):
        return {"candles": _candles(80)}

    monkeypatch.setattr("app.services.data.service.market_data.get_history_auto", _auto)

    r = client.get("/api/analysis/chart-markup", headers=auth, params={"symbol": "NSE:TEST", "interval": "1d", "period": "3mo"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "NSE:TEST"
    assert body["candle_count"] == 80
    assert "markers" in body
    assert "levels" in body
    assert "trend" in body


def test_chart_markup_router_alias(client: TestClient, auth: dict, monkeypatch) -> None:
    async def _auto(symbol, *, interval="1d", period="3mo", provider=None, chain=None):
        return {"candles": _candles(60)}

    monkeypatch.setattr("app.services.data.service.market_data.get_history_auto", _auto)

    r = client.get("/api/chart-markup", headers=auth, params={"symbol": "NSE:TEST"})
    assert r.status_code == 200, r.text
    assert r.json()["candle_count"] == 60
