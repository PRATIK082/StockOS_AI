"""Tests for the Vibe Trading Chat engine and SSE route.

The engine streams real StockOS data in stages; tests inject fake market/
prediction/signals services and a stub LLM so no network is touched.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

from app.main import app  # noqa: E402
from app.services.vibe import engine as vibe_engine_mod  # noqa: E402
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


def _fake_candles(n: int = 60, base: float = 100.0) -> list[dict]:
    import numpy as np

    rng = np.random.default_rng(7)
    closes = base * np.cumprod(1 + rng.normal(0.0003, 0.015, n))
    out = []
    for i, c in enumerate(closes):
        out.append(
            {
                "ts": f"2025-01-{i % 28 + 1:02d}T00:00:00",
                "open": float(c),
                "high": float(c * 1.01),
                "low": float(c * 0.99),
                "close": float(c),
                "volume": 1_000_000,
            }
        )
    return out


class _FakeMarket:
    async def get_quote(self, symbol: str, provider: str | None = None) -> dict:
        if symbol == "NSE:BOGUS":
            return {}
        return {"symbol": symbol, "price": 123.45, "day_change_pct": 0.012, "currency": "INR", "provider": "yahoo"}

    async def get_history(self, symbol: str, *, interval: str = "1d", period: str = "1y") -> dict:
        return {"symbol": symbol, "interval": interval, "period": period, "candles": _fake_candles()}

    async def get_history_auto(self, symbol: str, *, interval: str = "1d", period: str = "3mo") -> dict:
        return {"symbol": symbol, "interval": interval, "period": period, "candles": _fake_candles()}

    async def get_fundamentals(self, symbol: str) -> dict:
        return {"base": {}}

    async def get_option_chain(self, symbol: str, *, expiry: str | None = None) -> dict:
        return {"symbol": symbol, "spot_price": 123.45, "calls": [], "puts": []}


class _FakeSignals:
    async def signals(self, symbol: str) -> dict:
        return {"bias": "CALL", "strategy": "call", "max_pain": 122.0, "atm_iv": 0.19, "spot_price": 123.45, "expiry": "2026-08-25"}


@pytest.fixture
def engine(monkeypatch) -> vibe_engine_mod.VibeChatEngine:
    fake = _FakeMarket()
    eng = vibe_engine_mod.VibeChatEngine(market_service=fake, prediction=None, signals=_FakeSignals())
    eng.prediction = None  # replaced below via fake prediction
    return eng


async def _collect(eng: vibe_engine_mod.VibeChatEngine, message: str):
    return [ev async for ev in eng.stream(message, provider="ollama")]


def test_plan_emitted_first(monkeypatch) -> None:
    import asyncio

    async def _chat(messages, **kwargs):
        return "ok"

    monkeypatch.setattr(vibe_engine_mod, "gateway", type("G", (), {"chat": _chat})())
    eng = vibe_engine_mod.VibeChatEngine(market_service=_FakeMarket(), prediction=None, signals=_FakeSignals())
    evs = asyncio.run(_collect(eng, "What about NSE:RELIANCE?"))
    assert evs[0]["type"] == "plan"
    assert [p["key"] for p in evs[0]["plan"]] == ["symbol", "quote", "technical", "options", "prediction", "answer"]
    assert evs[1]["type"] == "stage" and evs[1]["key"] == "symbol"


def test_pipeline_full_flow(monkeypatch) -> None:
    import asyncio

    async def _chat(messages, **kwargs):
        return "**Verdict** — looks constructive."

    monkeypatch.setattr(vibe_engine_mod, "gateway", type("G", (), {"chat": _chat})())
    eng = vibe_engine_mod.VibeChatEngine(market_service=_FakeMarket(), prediction=None, signals=_FakeSignals())
    evs = asyncio.run(_collect(eng, "Analyze NSE:RELIANCE"))
    by_key = {ev["key"]: ev for ev in evs if ev.get("type") == "stage"}
    assert by_key["symbol"]["status"] == "done"
    assert by_key["quote"]["data"]["quote"]["price"] == 123.45
    assert by_key["technical"]["data"]["last_close"] > 0
    assert by_key["technical"]["data"]["rsi"] is not None
    assert by_key["options"]["data"]["bias"] == "CALL"
    assert by_key["prediction"]["data"]["current_price"] > 0
    assert by_key["prediction"]["data"]["trading_stats"]
    answer = next(ev for ev in evs if ev["type"] == "answer")
    assert "Verdict" in answer["data"]["answer"]
    assert answer["data"]["confidence"] > 0
    assert answer["data"]["symbol"] == "NSE:RELIANCE"


def test_unresolved_symbol_skips_stages(monkeypatch) -> None:
    import asyncio

    async def _chat(messages, **kwargs):
        return "No ticker."

    monkeypatch.setattr(vibe_engine_mod, "gateway", type("G", (), {"chat": _chat})())
    eng = vibe_engine_mod.VibeChatEngine(market_service=_FakeMarket(), prediction=None, signals=_FakeSignals())
    evs = asyncio.run(_collect(eng, "What is the outlook for NSE:BOGUS?"))
    symbol_stage = next(ev for ev in evs if ev.get("type") == "stage" and ev["key"] == "symbol")
    assert symbol_stage["status"] == "skipped"
    answer = next(ev for ev in evs if ev["type"] == "answer")
    assert answer["data"]["symbol"] is None


def test_deterministic_verdict_fallback(monkeypatch) -> None:
    import asyncio

    async def _raise(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(vibe_engine_mod, "gateway", type("G", (), {"chat": _raise})())
    eng = vibe_engine_mod.VibeChatEngine(market_service=_FakeMarket(), prediction=None, signals=_FakeSignals())
    evs = asyncio.run(_collect(eng, "Analyze NSE:RELIANCE"))
    answer = next(ev for ev in evs if ev["type"] == "answer")
    assert "Deterministic engine" in answer["data"]["answer"]
    assert "BUY" in answer["data"]["answer"] or "HOLD" in answer["data"]["answer"] or "SELL" in answer["data"]["answer"]


def test_vibe_route_streams_events(client: TestClient, monkeypatch) -> None:
    """The SSE route surfaces the pipeline as data: frames."""
    events: list[dict] = []

    async def _fake_stream(message, *, provider=None):
        yield {"type": "plan", "plan": [{"key": "quote", "label": "Quote"}]}
        yield {"type": "stage", "status": "done", "key": "quote", "data": {"quote": {"price": 10.0}}}
        yield {"type": "answer", "data": {"answer": "ok", "confidence": 0.5, "symbol": "NSE:X", "sources": []}}

    monkeypatch.setattr(vibe_engine_mod, "vibe_chat_engine", type("E", (), {"stream": _fake_stream})())
    r = client.post("/api/chat/vibe", json={"message": "Analyze NSE:X"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    for line in r.text.splitlines():
        if line.startswith("data: "):
            events.append(__import__("json").loads(line[6:]))
    assert events[0]["type"] == "plan"
    assert events[1]["type"] == "stage"
    assert events[2]["type"] == "answer"
