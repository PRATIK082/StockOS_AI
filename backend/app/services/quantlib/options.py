"""Options analytics: Black-Scholes implied volatility (Newton solver on the
existing OptionsEngine) and a dict-form greeks surface. Finite-safe."""

from __future__ import annotations

from app.services.options.engine import OptionsEngine


def implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    option_type: str = "call",
    max_iter: int = 60,
    tol: float = 1e-6,
) -> float | None:
    """Newton-Raphson implied vol (bounded [1e-4, 5]). Returns None if the
    price is outside the arbitrage-free range for any vol."""
    engine = OptionsEngine()
    if market_price <= 0 or spot <= 0 or strike <= 0 or time_to_expiry <= 0:
        return None
    intrinsic = max(spot - strike, 0) if option_type.lower() == "call" else max(strike - spot, 0)
    if market_price < intrinsic:
        return None
    vol = 0.3
    for _ in range(max_iter):
        price = engine.theoretical_price(spot, strike, time_to_expiry, vol, option_type)
        greeks = engine.calculate_greeks(spot, strike, time_to_expiry, vol, option_type)
        vega = greeks.vega * 100.0  # engine scales vega /100
        diff = price - market_price
        if abs(diff) < tol:
            return float(vol)
        if not np_isfinite(vega) or vega <= 1e-12:
            return None
        vol -= diff / vega
        if not np_isfinite(vol):
            return None
        vol = min(max(vol, 1e-4), 5.0)
    return float(vol) if np_isfinite(vol) else None


def greeks(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    option_type: str = "call",
    dividend_yield: float = 0.0,
) -> dict:
    """Full greeks surface (delta/gamma/theta/vega/rho) + price as a dict."""
    engine = OptionsEngine()
    g = engine.calculate_greeks(spot, strike, time_to_expiry, volatility, option_type, dividend_yield)
    price = engine.theoretical_price(spot, strike, time_to_expiry, volatility, option_type, dividend_yield)
    return {
        "price": float(price),
        "delta": float(g.delta),
        "gamma": float(g.gamma),
        "theta": float(g.theta),
        "vega": float(g.vega),
        "rho": float(g.rho),
        "spot": spot,
        "strike": strike,
        "time_to_expiry_years": time_to_expiry,
        "volatility": volatility,
        "option_type": option_type.lower(),
    }


def np_isfinite(x: float) -> bool:
    import math

    return math.isfinite(x)
