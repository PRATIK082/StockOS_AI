"""Quantlib HTTP router: risk, portfolio, cashflow and options analytics."""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user

router = APIRouter(prefix="/quantlib", tags=["quantlib"])


@router.post("/risk")
async def quantlib_risk(
    body: dict[str, Any],
    current_user=Depends(get_current_user),
):
    """Risk analytics on a returns series: parametric/cornish-fisher/EVT VaR,
    expected shortfall and EWMA vol. ``returns`` is a list of floats."""
    returns = body.get("returns")
    if not isinstance(returns, list) or not returns:
        raise HTTPException(status_code=422, detail="returns list required")
    from app.services.quantlib.risk import cornish_fisher_var, evt_var, ewma_vol, parametric_var

    level = body.get("level", 0.05)
    out = {
        "n": len(returns),
        "level": level,
        "parametric_var": parametric_var(returns, level, body.get("horizon", 1)),
        "cornish_fisher_var": cornish_fisher_var(returns, level),
        "evt_var": evt_var(returns, level, body.get("threshold_pct", 0.95)),
        "ewma_vol": ewma_vol(returns, body.get("lambda", 0.94)),
    }
    return out


@router.post("/portfolio")
async def quantlib_portfolio(
    body: dict[str, Any],
    current_user=Depends(get_current_user),
):
    """Black-Litterman view blending or Brinson attribution. ``method`` picks
    the engine; payload fields match the engine's arguments."""
    method = body.get("method", "black_litterman")
    from app.services.quantlib.portfolio import black_litterman, brinson_attribution

    if method == "black_litterman":
        if not body.get("returns_mean") or not body.get("cov") or not body.get("market_weights"):
            raise HTTPException(status_code=422, detail="returns_mean, cov and market_weights required")
        return black_litterman(
            body["returns_mean"],
            body["cov"],
            body["market_weights"],
            body.get("views", []),
            risk_free=body.get("risk_free", 0.0),
            tau=body.get("tau", 0.05),
        )
    if method == "brinson":
        for key in ("portfolio_returns", "benchmark_returns", "portfolio_weights", "benchmark_weights"):
            if not body.get(key):
                raise HTTPException(status_code=422, detail=f"{key} required")
        return brinson_attribution(
            body["portfolio_returns"],
            body["benchmark_returns"],
            body["portfolio_weights"],
            body["benchmark_weights"],
        )
    raise HTTPException(status_code=422, detail="method must be black_litterman or brinson")


@router.post("/cashflow")
async def quantlib_cashflow(
    body: dict[str, Any],
    current_user=Depends(get_current_user),
):
    """NPV / IRR / XIRR. ``tool`` in {npv, irr, xirr}; ``amounts`` required
    (``dates`` for xirr)."""
    from app.services.quantlib.cashflow import irr, npv, xirr

    tool = body.get("tool", "npv")
    amounts = body.get("amounts")
    if not isinstance(amounts, list) or not amounts:
        raise HTTPException(status_code=422, detail="amounts list required")
    try:
        if tool == "npv":
            return {"tool": "npv", "result": npv(body.get("rate", 0.0), amounts)}
        if tool == "irr":
            return {"tool": "irr", "result": irr(amounts, body.get("guess", 0.1))}
        if tool == "xirr":
            if not body.get("dates"):
                raise HTTPException(status_code=422, detail="dates required for xirr")
            return {"tool": "xirr", "result": xirr(amounts, body["dates"], body.get("guess", 0.1))}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    raise HTTPException(status_code=422, detail="tool must be npv, irr or xirr")


@router.post("/options")
async def quantlib_options(
    body: dict[str, Any],
    current_user=Depends(get_current_user),
):
    """Option pricing analytics: ``tool`` in {greeks, implied_vol}. greeks
    needs spot/strike/time_to_expiry/volatility; implied_vol needs
    market_price plus the same."""
    from app.services.quantlib.options import greeks as greeks_fn
    from app.services.quantlib.options import implied_volatility as iv_fn

    tool = body.get("tool", "greeks")
    spot, strike, tte = body.get("spot"), body.get("strike"), body.get("time_to_expiry")
    if spot is None or strike is None or tte is None:
        raise HTTPException(status_code=422, detail="spot, strike and time_to_expiry required")
    otype = body.get("option_type", "call")
    if tool == "greeks":
        return greeks_fn(spot, strike, tte, body.get("volatility", 0.25), otype)
    if tool == "implied_vol":
        price = body.get("market_price")
        if price is None:
            raise HTTPException(status_code=422, detail="market_price required")
        iv = iv_fn(price, spot, strike, tte, otype)
        return {"implied_volatility": iv}
    raise HTTPException(status_code=422, detail="tool must be greeks or implied_vol")
