"""Tests for the Agent Autopilot (multi-agent supervisor).

Covers: router auth/state/toggle/config, sentinel decision logic (TP / SL /
trail), the risk gate, option-strategy leg building, an end-to-end mission run
(orders + tracked F&O + journal + telemetry), monitor-only mode, and the
scheduler `autopilot` playbook. All market access is monkeypatched — no live
feeds, no fabricated production data.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import asyncio
    from app.main import app

    from app.db.base import Base
    from app.db.session import engine

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "autopilot@test.dev", "username": "autopilotuser", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post(
            "/api/auth/login",
            json={"identifier": "autopilotuser", "password": "secret123"},
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------------- #
# Helpers
# ------------------------------------------------------------------------- #


def _rising_history(n: int = 60):
    """60-bar steady uptrend used only where a real history is required."""
    candles = []
    for i in range(n):
        c = 100.0 + i * 1.5
        candles.append({
            "ts": f"2026-01-{1 + i % 28:02d} 09:30",
            "open": c,
            "high": c * 1.01,
            "low": c * 0.99,
            "close": c,
            "volume": 100000,
        })
    return {"symbol": "NSE:XYZ", "interval": "1d", "candles": candles}


def _patch_signal_long(monkeypatch):
    """Force the signal agent to return one deterministic LONG candidate.

    This keeps the e2e/monitor/scheduler tests focused on *orchestration*
    (all 7 phases + a paper BUY fill) instead of tuning synthetic OHLC so
    `_technical_quick` happens to classify it LONG.
    """
    from app.services.autopilot import agents
    from app.services.autopilot import engine as autopilot_engine_mod

    async def fake_signal(config, limit=8):
        return {
            "agent": "signal",
            "market": config.market,
            "scanners": config.scanners,
            "candidates": [
                {
                    "symbol": "NSE:XYZ",
                    "strength": 0.85,
                    "scanners": [config.scanners[0]],
                    "reasons": ["Momentum 1M", "SMA20>50"],
                    "direction": "LONG",
                    "strength2": 0.85,
                }
            ],
        }

    monkeypatch.setattr(agents, "signal_agent", fake_signal)
    monkeypatch.setattr(autopilot_engine_mod, "signal_agent", fake_signal)


def _patch_market(monkeypatch):
    """Patch the market facade + scanner + options signals for deterministic missions."""
    from app.services.data.service import market_data
    from app.services.scanners.engine import MarketScanner, ScanResult

    async def fake_history(self, symbol, *args, **kwargs):
        return _rising_history()

    async def fake_quote(symbol, *args, **kwargs):
        return {"price": 1500.0, "last_price": 1500.0, "bid": 1499.0, "ask": 1501.0}

    async def fake_chain(symbol, *args, **kwargs):
        return {
            "symbol": symbol,
            "spot_price": 1500.0,
            "expiry": "2026-09-24",
            "expiries": ["2026-09-24"],
            "calls": [{"strike": 1490.0, "last": 58.0, "iv": 0.18}, {"strike": 1500.0, "last": 55.0, "iv": 0.18}, {"strike": 1510.0, "last": 52.0, "iv": 0.18}],
            "puts": [{"strike": 1490.0, "last": 40.0, "iv": 0.20}, {"strike": 1500.0, "last": 45.0, "iv": 0.20}, {"strike": 1510.0, "last": 48.0, "iv": 0.20}],
        }

    async def fake_scan(self, scanner_type, market="india", limit=20):
        return [
            ScanResult(
                symbol="NSE:XYZ",
                name="XYZ",
                price=1500.0,
                change_pct=2.0,
                volume=1_000_000,
                signal_strength=0.9,
                matched_criteria=["Momentum 1M"],
            )
        ]

    monkeypatch.setattr(market_data, "get_history_auto", fake_history)
    monkeypatch.setattr(market_data, "get_quote", fake_quote)
    monkeypatch.setattr(market_data, "get_option_chain", fake_chain)
    monkeypatch.setattr(MarketScanner, "scan", fake_scan)

    from app.services.options.signals import OptionsSignalsService

    async def fake_signals(self, symbol, expiry=None):
        return {
            "symbol": symbol,
            "expiry": "2026-09-24",
            "spot_price": 1500.0,
            "max_pain": 1490.0,
            "premium_put_call": 1.2,
            "iv_skew": 0.03,
            "atm_iv": 0.18,
            "avg_iv": 0.19,
            "bias": "CALL",
            "strategy": "bullish",
            "recommendation": "Momentum CE buys favoured.",
        }

    monkeypatch.setattr(OptionsSignalsService, "signals", fake_signals)


# ------------------------------------------------------------------------- #
# Router: auth / state / toggle / config
# ------------------------------------------------------------------------- #


def test_autopilot_requires_auth(client):
    assert client.get("/api/autopilot/state").status_code == 401
    assert client.post("/api/autopilot/toggle", json={"enabled": True}).status_code == 401
    assert client.post("/api/autopilot/config", json={"market": "us"}).status_code == 401
    assert client.post("/api/autopilot/run").status_code == 401
    assert client.get("/api/autopilot/runs").status_code == 401


def test_state_defaults(client, auth_headers):
    r = client.get("/api/autopilot/state", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["mode"] == "PAPER"
    assert body["config"]["market"] == "india"
    assert body["config"]["take_profit_pct"] == 5.0
    assert body["config"]["option_enabled"] is True


def test_toggle_and_config_patch(client, auth_headers):
    r = client.post("/api/autopilot/toggle", json={"enabled": True}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    s = client.get("/api/autopilot/state", headers=auth_headers).json()
    assert s["enabled"] is True

    r2 = client.post(
        "/api/autopilot/config",
        json={"market": "us", "take_profit_pct": 8.5, "scanners": ["breakout"]},
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    cfg = r2.json()["config"]
    assert cfg["market"] == "us"
    assert cfg["take_profit_pct"] == 8.5
    assert cfg["scanners"] == ["breakout"]
    # untouched fields keep defaults
    assert cfg["option_enabled"] is True

    client.post("/api/autopilot/toggle", json={"enabled": False}, headers=auth_headers)


def test_config_validation(client, auth_headers):
    r = client.post("/api/autopilot/config", json={"entry_qty": -5}, headers=auth_headers)
    assert r.status_code == 422


# ------------------------------------------------------------------------- #
# Sentinel decision logic (unit-level)
# ------------------------------------------------------------------------- #


def _position(symbol, qty, avg):
    from decimal import Decimal

    from app.brokers.interface import BrokerPosition, ProductType

    return BrokerPosition(
        symbol=symbol,
        exchange=symbol.split(":")[0],
        product=ProductType.CNC,
        quantity=Decimal(str(qty)),
        average_price=Decimal(str(avg)),
        market_value=Decimal(str(qty * avg)),
        unrealised_pnl=Decimal("0.00"),
        realised_pnl=Decimal("0.00"),
    )


@pytest.mark.parametrize(
    "price,tp,sl,expected",
    [
        (108.0, 5.0, -3.0, "take_profit"),
        (90.0, 5.0, -3.0, "stop_loss"),
        (101.0, 5.0, -3.0, "HOLD"),
    ],
)
def test_sentinel_take_profit_stop_loss_hold(monkeypatch, price, tp, sl, expected):
    from app.brokers.paper import PaperBroker
    from app.services.autopilot.agents import sentinel_agent
    from app.services.autopilot.config import AutopilotConfig
    from app.services.data.service import market_data

    async def fake_positions(self):
        return [_position("NSE:AAA", 10, 100)]

    async def fake_quote(symbol, *a, **k):
        return {"price": price, "last_price": price}

    async def fake_history(self, symbol, *a, **k):
        return _rising_history()

    monkeypatch.setattr(PaperBroker, "positions", fake_positions)
    monkeypatch.setattr(market_data, "get_quote", fake_quote)
    monkeypatch.setattr(market_data, "get_history_auto", fake_history)

    config = AutopilotConfig(take_profit_pct=tp, stop_loss_pct=sl, trail_enabled=True, trail_drop_pct=1.0)
    import asyncio

    from app.services.memory.store import memory_store

    asyncio.run(memory_store.set("u-sentinel", "autopilot:trail:NSE:AAA", {"peak_pct": 1.0}, kind="autopilot", scope="trail"))
    out = asyncio.run(sentinel_agent("u-sentinel", config))

    assert len(out["monitored"]) == 1
    row = out["monitored"][0]
    if expected == "HOLD":
        assert row["action"] == "HOLD"
        assert out["proposals"] == []
    else:
        assert row["action"] == "SELL"
        assert row["reason"] == expected
        assert out["proposals"][0]["action"] == expected
        assert out["proposals"][0]["side"] == "SELL"


def test_sentinel_trail_stop(monkeypatch):
    from app.brokers.paper import PaperBroker
    from app.services.autopilot.agents import sentinel_agent
    from app.services.autopilot.config import AutopilotConfig
    from app.services.data.service import market_data

    async def fake_positions(self):
        return [_position("NSE:BBB", 10, 100)]

    monkeypatch.setattr(PaperBroker, "positions", fake_positions)
    monkeypatch.setattr(market_data, "get_history_auto", lambda self, symbol, *a, **k: _rising_history())

    async def fake_quote_first(symbol, *a, **k):
        return {"price": 109.0, "last_price": 109.0}

    async def fake_quote_second(symbol, *a, **k):
        return {"price": 105.5, "last_price": 105.5}

    monkeypatch.setattr(market_data, "get_quote", fake_quote_first)
    config = AutopilotConfig(take_profit_pct=20.0, stop_loss_pct=-10.0, trail_enabled=True, trail_drop_pct=1.0)
    first = __import__("asyncio").run(sentinel_agent("u-trail", config))
    assert first["proposals"] == []  # +9% under TP20, peak stored

    monkeypatch.setattr(market_data, "get_quote", fake_quote_second)
    second = __import__("asyncio").run(sentinel_agent("u-trail", config))
    assert second["monitored"][0]["action"] == "SELL"
    assert second["proposals"][0]["action"] == "trail_stop"


# ------------------------------------------------------------------------- #
# Risk gate
# ------------------------------------------------------------------------- #


def test_riskgate_rejects_unheld_sell(monkeypatch):
    from app.services.autopilot.agents import Proposal, riskgate_agent
    from app.services.autopilot.config import AutopilotConfig

    async def fake_positions(self):
        return []

    monkeypatch.setattr("app.brokers.paper.PaperBroker.positions", fake_positions)

    out = __import__("asyncio").run(
        riskgate_agent(
            "u-risk",
            AutopilotConfig(),
            [Proposal(symbol="NSE:NOTHELD", side="SELL", action="stop_loss", reason="sl", qty=5)],
        )
    )
    assert len(out["approved"]) == 0
    assert out["rejected"][0]["reason"].startswith("no open position")


# ------------------------------------------------------------------------- #
# Option strategy agent
# ------------------------------------------------------------------------- #


def test_optionstrategy_builds_ce_play(monkeypatch):
    from app.services.autopilot.agents import optionstrategy_agent
    from app.services.autopilot.config import AutopilotConfig

    from app.services.options.signals import OptionsSignalsService

    async def fake_signals(self, symbol, expiry=None):
        return {
            "symbol": symbol,
            "expiry": "2026-09-24",
            "spot_price": 2100.0,
            "max_pain": 2120.0,
            "premium_put_call": 0.7,
            "iv_skew": -0.02,
            "atm_iv": 0.16,
            "avg_iv": 0.17,
            "bias": "CALL",
            "strategy": "bullish",
            "recommendation": "Momentum CALL buys favoured.",
        }

    async def fake_chain(symbol, *a, **k):
        return {
            "symbol": symbol,
            "spot_price": 2100.0,
            "expiry": "2026-09-24",
            "expiries": ["2026-09-24"],
            "calls": [{"strike": 2080.0, "last": 80.0}, {"strike": 2100.0, "last": 62.0}, {"strike": 2120.0, "last": 46.0}],
            "puts": [{"strike": 2080.0, "last": 30.0}, {"strike": 2100.0, "last": 45.0}],
        }

    monkeypatch.setattr(OptionsSignalsService, "signals", fake_signals)
    from app.services.data.service import market_data

    monkeypatch.setattr(market_data, "get_option_chain", fake_chain)

    config = AutopilotConfig(watchlist=["NSE:TCS"], option_max_plays=2, option_lots=1)
    out = __import__("asyncio").run(optionstrategy_agent(config, []))
    assert len(out["plays"]) == 1
    play = out["plays"][0]
    assert play["symbol"] == "NSE:TCS"
    assert play["option_type"] == "CE"
    assert play["strike"] == 2100.0
    assert play["bias"] == "CALL"
    assert play["lots"] == 1


# ------------------------------------------------------------------------- #
# End-to-end mission (router)
# ------------------------------------------------------------------------- #


def test_e2e_mission_run(client, auth_headers, monkeypatch):
    _patch_market(monkeypatch)
    _patch_signal_long(monkeypatch)

    r = client.post("/api/autopilot/run", headers=auth_headers)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] in ("completed", "halted"), run["error"]
    phases = [n["phase"] for n in run["nodes"]]
    for expected in ("sentinel", "signal", "optionstrategy", "riskgate", "execute", "selfreview", "debrief"):
        assert expected in phases, f"missing phase {expected} in {phases}"

    execute = next(n for n in run["nodes"] if n["phase"] == "execute")["evidence"]
    assert len(execute["fills"]) >= 1  # NSE:XYZ BUY
    assert len(execute["option_tracks"]) >= 1  # auto-tracked CE play
    summary = run["summary"]
    assert summary["n_option_tracks"] >= 1

    # Fill appears in the order history (analytics parity)
    orders = client.get("/api/v1/orders", headers=auth_headers)
    assert orders.status_code == 200
    syms = [o["symbol"] for o in orders.json()]
    assert "NSE:XYZ" in syms

    # Parsed signal persisted in memory
    s = client.get("/api/autopilot/state", headers=auth_headers).json()
    assert s["last_review"] is not None
    assert "score" in s["last_review"]

    # Mission history recorded
    h = client.get("/api/autopilot/runs", headers=auth_headers)
    assert h.status_code == 200
    assert len(h.json()["runs"]) >= 1

    # Run detail endpoint round-trips
    detail = client.get(f"/api/autopilot/runs/{run['id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == run["id"]


def test_monitor_only_skips_hunting(client, auth_headers, monkeypatch):
    _patch_market(monkeypatch)
    _patch_signal_long(monkeypatch)
    r = client.post("/api/autopilot/run?monitor_only=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["mission"] == "monitor"
    phases = [n["phase"] for n in run["nodes"]]
    assert "signal" not in phases
    assert "optionstrategy" not in phases
    assert "sentinel" in phases
    assert "selfreview" in phases


def test_run_playbook_autopilot_requires_user(client):
    from app.services.scheduler.runner import run_playbook

    out = __import__("asyncio").run(run_playbook({"type": "autopilot"}))
    assert "error" in out
    assert "user_id" in out["error"]

    from app.api.routers.scheduled import _validate_playbook

    _validate_playbook({"type": "autopilot"})  # no symbols required -> no 422


def test_run_playbook_autopilot_with_user(client, auth_headers, monkeypatch):
    _patch_market(monkeypatch)
    _patch_signal_long(monkeypatch)
    from app.api.routers.scheduled import _validate_playbook
    from app.services.scheduler.runner import run_playbook

    pb = {"type": "autopilot", "market": "india", "take_profit_pct": 6.0}
    _validate_playbook(pb)
    import asyncio

    from app.db.session import SessionFactory
    from app.db.models import User
    from sqlalchemy import select

    async def _get_uid():
        async with SessionFactory() as session:
            row = await session.scalar(select(User).where(User.username == "autopilotuser"))
            return row.id

    uid = asyncio.run(_get_uid())
    out = asyncio.run(run_playbook(pb, user_id=uid))
    assert "error" not in out, out
    assert out["type"] == "autopilot"
    assert out["node_phases"][0] == "sentinel"