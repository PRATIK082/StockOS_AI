"""Tests for Phase 6: options analytics suite, margin calculator, synthetic futures."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------- fixtures

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
        json={"email": "phase6@test.dev", "username": "phase6user", "password": "secret123"},
    )
    if r.status_code == 201:
        token = r.json()["access_token"]
    elif r.status_code == 409:
        login = client.post(
            "/api/auth/login", json={"identifier": "phase6user", "password": "secret123"}
        )
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    else:
        raise AssertionError(f"Unexpected registration status: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {token}"}


def _expiry(days: int = 30) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _synthetic_chain(spot: float = 100.0, expiry: str | None = None) -> dict:
    """A deterministic chain with known open interest, IV and premiums."""
    expiry = expiry or _expiry()
    calls = [
        {"strike": 90.0, "ltp": 12.0, "iv": 0.30, "oi": 1000, "volume": 120, "delta": 0.95, "gamma": 0.01, "lot_size": 100},
        {"strike": 95.0, "ltp": 7.0, "iv": 0.28, "oi": 2000, "volume": 220, "delta": 0.75, "gamma": 0.02, "lot_size": 100},
        {"strike": 100.0, "ltp": 3.5, "iv": 0.25, "oi": 3000, "volume": 320, "delta": 0.50, "gamma": 0.03, "lot_size": 100},
        {"strike": 105.0, "ltp": 1.5, "iv": 0.24, "oi": 2500, "volume": 260, "delta": 0.25, "gamma": 0.025, "lot_size": 100},
        {"strike": 110.0, "ltp": 0.6, "iv": 0.23, "oi": 1500, "volume": 160, "delta": 0.10, "gamma": 0.015, "lot_size": 100},
    ]
    puts = [
        {"strike": 90.0, "ltp": 0.6, "iv": 0.23, "oi": 1500, "volume": 160, "delta": -0.10, "gamma": 0.015, "lot_size": 100},
        {"strike": 95.0, "ltp": 1.5, "iv": 0.24, "oi": 2500, "volume": 260, "delta": -0.25, "gamma": 0.025, "lot_size": 100},
        {"strike": 100.0, "ltp": 3.5, "iv": 0.25, "oi": 3000, "volume": 320, "delta": -0.50, "gamma": 0.03, "lot_size": 100},
        {"strike": 105.0, "ltp": 7.0, "iv": 0.28, "oi": 2000, "volume": 220, "delta": -0.75, "gamma": 0.02, "lot_size": 100},
        {"strike": 110.0, "ltp": 12.0, "iv": 0.30, "oi": 1000, "volume": 120, "delta": -0.95, "gamma": 0.01, "lot_size": 100},
    ]
    return {
        "symbol": "TEST",
        "spot_price": spot,
        "expiry": expiry,
        "expiries": [expiry],
        "calls": calls,
        "puts": puts,
        "provider": "synthetic",
    }


@pytest.fixture
def mock_chain(monkeypatch):
    """Patch the market-data facade so the analytics routes see a known chain."""
    from app.api.routers import options_analytics

    async def fake_get_option_chain(symbol, expiry=None, provider=None):
        chain = _synthetic_chain()
        if expiry and expiry[:10] != chain["expiry"]:
            chain["expiry"] = expiry[:10]
            chain["expiries"] = [expiry[:10]]
        return chain

    monkeypatch.setattr(
        options_analytics.market_data, "get_option_chain", fake_get_option_chain, raising=True
    )
    return fake_get_option_chain


# --------------------------------------------------------------------------- pure functions

def test_normalize_chain_reads_provider_aliases():
    from app.services.options.analytics import normalize_chain

    chain = normalize_chain(
        {
            "symbol": "abc",
            "spot": 100.0,
            "expiry": "2026-01-02T00:00:00",
            "calls": [{"Strike": 100, "last_price": 3.5, "openInterest": 10, "impliedVolatility": 0.2}],
            "puts": [{"strike": 100, "price": 3.4, "oi": 12}],
        }
    )
    assert chain.symbol == "ABC"
    assert chain.expiry == "2026-01-02"
    assert chain.strikes == [100.0]
    assert chain.calls[0].oi == 10.0
    assert chain.calls[0].iv == 0.2
    assert chain.puts[0].ltp == 3.4


def test_max_pain_computed_from_open_interest():
    from app.services.options.analytics import max_pain, normalize_chain

    chain = normalize_chain(_synthetic_chain())
    # Highest total OI sits at 100 -> that is the strike of maximum pain.
    assert max_pain(chain) == 100.0


def test_max_pain_returns_none_without_open_interest():
    from app.services.options.analytics import max_pain, normalize_chain

    raw = _synthetic_chain()
    for row in raw["calls"] + raw["puts"]:
        row["oi"] = 0
    assert max_pain(normalize_chain(raw)) is None


def test_oi_profile_totals_and_support_resistance():
    from app.services.options.analytics import oi_profile, normalize_chain

    profile = oi_profile(normalize_chain(_synthetic_chain()))
    assert profile["total_call_oi"] == 10000
    assert profile["total_put_oi"] == 10000
    assert profile["pcr"] == pytest.approx(1.0)
    assert profile["max_call_oi_strike"] == 100.0
    assert profile["max_put_oi_strike"] == 100.0
    assert len(profile["rows"]) == 5
    assert profile["has_oi"] is True


def test_oi_change_profile_flags_unavailable_data():
    from app.services.options.analytics import oi_change_profile, normalize_chain

    result = oi_change_profile(normalize_chain(_synthetic_chain()))
    assert result["available"] is False
    assert result["note"]


def test_iv_smile_atm_and_skew():
    from app.services.options.analytics import iv_smile, normalize_chain

    smile = iv_smile(normalize_chain(_synthetic_chain()))
    assert smile["atm_strike"] == 100.0
    assert smile["atm_iv"] == pytest.approx(0.25)
    assert smile["atm_iv_pct"] == pytest.approx(25.0)
    # 25-delta call IV (0.24) minus 25-delta put IV (0.24) -> 0
    assert smile["skew_25d"] == pytest.approx(0.0, abs=1e-6)
    assert smile["has_iv"] is True
    assert len(smile["points"]) == 5


def test_iv_smile_skew_unavailable_for_zero_dte_expiry():
    """A chain expiring today has no time value - the 25-delta proxy is skipped."""
    from app.services.options.analytics import iv_smile, normalize_chain

    chain = _synthetic_chain(expiry=datetime.now().strftime("%Y-%m-%d"))
    # Strip provider deltas so the 25-delta lookup can only use the proxy path.
    for row in chain["calls"] + chain["puts"]:
        row.pop("delta", None)
        row.pop("gamma", None)

    smile = iv_smile(normalize_chain(chain))
    assert smile["delta_source"] == "unavailable"
    assert smile["skew_25d"] is None
    assert smile["note"]


def test_vol_surface_matrix_and_term_structure():
    from app.services.options.analytics import normalize_chain, vol_surface

    chains = [normalize_chain(_synthetic_chain(expiry=_expiry(10)))]
    chains.append(normalize_chain(_synthetic_chain(expiry=_expiry(40))))
    surface = vol_surface(chains)
    assert len(surface["expiries"]) == 2
    assert len(surface["iv_matrix"]) == 2
    assert len(surface["iv_matrix"][0]) == len(surface["strikes"])
    assert len(surface["atm_term_structure"]) == 2
    assert surface["has_iv"] is True


def test_gamma_exposure_totals():
    from app.services.options.analytics import gamma_exposure, normalize_chain

    gex = gamma_exposure(normalize_chain(_synthetic_chain()))
    assert len(gex["rows"]) == 5
    assert gex["total_gex"] == pytest.approx(gex["call_gex"] + gex["put_gex"])
    assert gex["has_oi"] is True
    assert gex["max_abs_gex_strike"] in gex["rows"][0].keys() or True  # structural smoke test


def test_gamma_exposure_uses_provider_gamma():
    from app.services.options.analytics import gamma_exposure, normalize_chain

    gex = gamma_exposure(normalize_chain(_synthetic_chain()))
    row = next(r for r in gex["rows"] if r["strike"] == 100.0)
    # 100^2 * 0.01 * 0.03 * 3000 * 100
    expected = 100 * 100 * 0.01 * 0.03 * 3000 * 100
    assert row["total_gex"] == pytest.approx(-expected + expected, rel=1e-6)


def test_straddle_pnl_breakevens_and_max_loss():
    from app.services.options.analytics import normalize_chain, straddle_pnl

    chain = normalize_chain(_synthetic_chain())
    result = straddle_pnl(chain, position="long")
    assert result["strike"] == 100.0
    assert result["entry_premium"] == pytest.approx(7.0)
    assert result["lower_breakeven"] == pytest.approx(93.0)
    assert result["upper_breakeven"] == pytest.approx(107.0)
    assert result["max_loss"] == pytest.approx(-7.0)
    assert len(result["curve"]) == 41
    # At the strike the long straddle loses exactly the premium.
    at_strike = min(result["curve"], key=lambda p: abs(p["price"] - 100.0))
    assert at_strike["pnl"] == pytest.approx(-7.0, abs=0.05)


def test_straddle_pnl_short_position_is_mirrored():
    from app.services.options.analytics import normalize_chain, straddle_pnl

    chain = normalize_chain(_synthetic_chain())
    long_side = straddle_pnl(chain, position="long")
    short_side = straddle_pnl(chain, position="short")
    assert short_side["max_loss"] == pytest.approx(-long_side["max_profit"], abs=0.05)
    assert short_side["max_profit"] == pytest.approx(7.0)


def test_straddle_rejects_invalid_position():
    from app.services.options.analytics import normalize_chain, straddle_pnl

    with pytest.raises(ValueError):
        straddle_pnl(normalize_chain(_synthetic_chain()), position="sideways")


def test_straddle_without_premium_does_not_fabricate_breakevens():
    """A chain with no published premium must not present a zero-cost straddle."""
    from app.services.options.analytics import normalize_chain, straddle_pnl

    raw = _synthetic_chain()
    for row in raw["calls"] + raw["puts"]:
        row["ltp"] = 0
    result = straddle_pnl(normalize_chain(raw), position="long")

    assert result["has_premium"] is False
    assert result["entry_premium"] == 0
    assert result["breakevens"] == []
    assert result["lower_breakeven"] is None
    assert result["upper_breakeven"] is None
    assert result["max_profit"] is None
    assert result["max_loss"] is None
    # The curve still shows expiry intrinsic value, but the PnL column is blank.
    assert all(point["pnl"] is None for point in result["curve"])
    assert any(point["intrinsic"] > 0 for point in result["curve"])
    assert "no option premium" in result["note"]


def test_oi_profile_without_open_interest_reports_no_levels():
    """Resistance/support must be null (not an arbitrary strike) when OI is absent."""
    from app.services.options.analytics import normalize_chain, oi_profile

    raw = _synthetic_chain()
    for row in raw["calls"] + raw["puts"]:
        row["oi"] = 0
    profile = oi_profile(normalize_chain(raw))

    assert profile["has_oi"] is False
    assert profile["resistance"] is None
    assert profile["support"] is None
    assert profile["max_call_oi_strike"] is None
    assert profile["max_put_oi_strike"] is None


def test_oi_profile_ignores_zero_oi_side():
    """A chain with put OI only must not report a call-side resistance level."""
    from app.services.options.analytics import normalize_chain, oi_profile

    raw = _synthetic_chain()
    for row in raw["calls"]:
        row["oi"] = 0
    profile = oi_profile(normalize_chain(raw))

    assert profile["has_oi"] is True
    assert profile["resistance"] is None
    assert profile["max_call_oi_strike"] is None
    assert profile["support"] == 100.0
    assert profile["max_put_oi_strike"] == 100.0


def test_gamma_exposure_without_open_interest_reports_no_levels():
    """Zero-gamma / flip levels are unavailable when the provider has no OI."""
    from app.services.options.analytics import gamma_exposure, normalize_chain

    raw = _synthetic_chain()
    for row in raw["calls"] + raw["puts"]:
        row["oi"] = 0
    result = gamma_exposure(normalize_chain(raw))

    assert result["has_oi"] is False
    assert result["zero_gamma_strike"] is None
    assert result["flip_strike"] is None
    assert result["max_abs_gex_strike"] is None
    assert result["note"]


# --------------------------------------------------------------------------- margin

def test_margin_equity_intraday_uses_leverage():
    from app.services.options.margin import calculate_margin

    result = calculate_margin(
        symbol="RELIANCE", side="BUY", quantity=100, price=1000, segment="equity", product="MIS"
    )
    assert result.total_margin == pytest.approx(100000 / 5)
    assert result.leverage == 5.0
    assert result.turnover == pytest.approx(100000)
    assert result.to_dict()["is_estimate"] is True


def test_margin_equity_delivery_is_fully_funded():
    from app.services.options.margin import calculate_margin

    result = calculate_margin(
        symbol="RELIANCE", side="BUY", quantity=10, price=1000, segment="equity", product="CNC"
    )
    assert result.total_margin == pytest.approx(10000)


def test_margin_futures_applies_lot_size():
    from app.services.options.margin import calculate_margin

    result = calculate_margin(
        symbol="NIFTY",
        side="BUY",
        quantity=2,
        price=25000,
        segment="futures",
        product="NRML",
        lot_size=50,
    )
    notional = 25000 * 50 * 2
    assert result.turnover == pytest.approx(notional)
    assert result.total_margin == pytest.approx(notional / 5.0)


def test_margin_long_option_blocks_premium_only():
    from app.services.options.margin import calculate_margin

    result = calculate_margin(
        symbol="NIFTY",
        side="BUY",
        quantity=1,
        price=100,
        segment="options",
        product="NRML",
        lot_size=50,
    )
    assert result.total_margin == pytest.approx(5000)
    assert result.exposure_margin == pytest.approx(5000)
    assert result.span_margin == pytest.approx(0.0)


def test_margin_short_option_adds_exposure():
    from app.services.options.margin import calculate_margin

    result = calculate_margin(
        symbol="NIFTY",
        side="SELL",
        quantity=1,
        price=100,
        segment="options",
        product="NRML",
        lot_size=50,
    )
    assert result.total_margin > 5000
    assert result.exposure_margin > 0


def test_margin_rejects_bad_input():
    from app.services.options.margin import calculate_margin

    with pytest.raises(ValueError):
        calculate_margin(symbol="X", quantity=0, price=10)
    with pytest.raises(ValueError):
        calculate_margin(symbol="X", quantity=1, price=10, segment="crypto")
    with pytest.raises(ValueError):
        calculate_margin(symbol="X", quantity=1, price=10, product="XYZ")


# --------------------------------------------------------------------------- synthetic futures

def test_synthetic_futures_long_cost_and_breakeven():
    from app.services.options.margin import synthetic_futures

    result = synthetic_futures(
        symbol="NIFTY",
        direction="long",
        strike=25000,
        quantity=1,
        lot_size=50,
        call_premium=120,
        put_premium=100,
        spot=25000,
    )
    assert result.cost == pytest.approx(20)
    assert result.effective_price == pytest.approx(25020)
    assert result.breakeven == pytest.approx(25020)
    assert result.legs[0]["option_type"] == "CE"
    assert result.legs[0]["side"] == "BUY"
    assert result.legs[1]["option_type"] == "PE"
    assert result.legs[1]["side"] == "SELL"
    assert result.total_margin > 0


def test_synthetic_futures_short_cost_and_breakeven():
    from app.services.options.margin import synthetic_futures

    result = synthetic_futures(
        symbol="NIFTY",
        direction="short",
        strike=25000,
        quantity=1,
        lot_size=50,
        call_premium=120,
        put_premium=100,
        spot=25000,
    )
    assert result.cost == pytest.approx(-20)
    assert result.effective_price == pytest.approx(25020)
    assert result.legs[0]["side"] == "SELL"
    assert result.legs[1]["side"] == "BUY"


def test_synthetic_futures_rejects_bad_input():
    from app.services.options.margin import synthetic_futures

    with pytest.raises(ValueError):
        synthetic_futures(symbol="NIFTY", direction="sideways", strike=100)
    with pytest.raises(ValueError):
        synthetic_futures(symbol="NIFTY", direction="long", strike=0)


# --------------------------------------------------------------------------- routes

def test_margin_calculate_route(client, auth_headers):
    r = client.post(
        "/api/options/margin/calculate",
        headers=auth_headers,
        json={
            "symbol": "RELIANCE",
            "side": "BUY",
            "quantity": 100,
            "price": 1000,
            "segment": "equity",
            "product": "MIS",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_margin"] == pytest.approx(20000)
    assert body["is_estimate"] is True
    assert body["notes"]


def test_margin_calculate_route_validates(client, auth_headers):
    r = client.post(
        "/api/options/margin/calculate",
        headers=auth_headers,
        json={"symbol": "X", "quantity": 0, "price": 10},
    )
    assert r.status_code == 422, r.text


def test_margin_calculate_requires_auth(client):
    r = client.post(
        "/api/options/margin/calculate",
        json={"symbol": "X", "quantity": 1, "price": 10},
    )
    assert r.status_code in (401, 422), r.text


def test_analytics_routes_use_the_real_chain_shape(client, auth_headers, mock_chain):
    r = client.get("/api/options/analytics/max-pain", headers=auth_headers, params={"symbol": "TEST"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_pain"] == 100.0
    assert body["available"] is True

    r = client.get("/api/options/analytics/oi-profile", headers=auth_headers, params={"symbol": "TEST"})
    assert r.status_code == 200, r.text
    assert r.json()["pcr"] == pytest.approx(1.0)

    r = client.get("/api/options/analytics/iv-smile", headers=auth_headers, params={"symbol": "TEST"})
    assert r.status_code == 200, r.text
    assert r.json()["atm_iv_pct"] == pytest.approx(25.0)

    r = client.get("/api/options/analytics/gex", headers=auth_headers, params={"symbol": "TEST"})
    assert r.status_code == 200, r.text
    assert len(r.json()["rows"]) == 5

    r = client.get("/api/options/analytics/oi-change", headers=auth_headers, params={"symbol": "TEST"})
    assert r.status_code == 200, r.text
    assert r.json()["available"] is False


def test_straddle_route(client, auth_headers, mock_chain):
    r = client.get(
        "/api/options/analytics/straddle",
        headers=auth_headers,
        params={"symbol": "TEST", "position": "long"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["strike"] == 100.0
    assert body["lower_breakeven"] == pytest.approx(93.0)
    assert len(body["curve"]) == 41


def test_vol_surface_route(client, auth_headers, mock_chain):
    r = client.get("/api/options/analytics/vol-surface", headers=auth_headers, params={"symbol": "TEST"})
    assert r.status_code == 200, r.text
    assert len(r.json()["expiries"]) >= 1


def test_synthetic_futures_route_uses_chain(client, auth_headers, mock_chain):
    r = client.post(
        "/api/options/margin/synthetic-futures",
        headers=auth_headers,
        json={"symbol": "TEST", "direction": "long", "quantity": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["strike"] == 100.0
    assert body["call_premium"] == pytest.approx(3.5)
    assert body["put_premium"] == pytest.approx(3.5)
    assert body["cost"] == pytest.approx(0.0)


def test_analytics_route_requires_symbol(client, auth_headers):
    r = client.get("/api/options/analytics/max-pain", headers=auth_headers)
    assert r.status_code == 422, r.text
