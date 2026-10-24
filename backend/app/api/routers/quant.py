"""Quant API: factors, factor evaluation, factor bench. Backtest v2 lives in
``analysis.py``; portfolio optimization and quantlib math tools are added here
in later phases on the same router."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services.data.service import market_data
from app.services.data.ohlcv import sanitize_history
from app.services.factors.analysis import build_panel, factor_bench, ic_analysis, quantile_returns
from app.services.factors.backtest import factor_portfolio_backtest
from app.services.factors.blend import composite_signal
from app.services.factors.registry import count_factors, list_factors

router = APIRouter(prefix="/quant", tags=["quant"])


class FactorAnalysisBody(BaseModel):
    symbols: List[str]
    factors: Optional[List[str]] = None
    interval: str = "1d"
    period: str = "2y"
    forward_days: int = 1
    n_quantiles: int = 5


class SignalBlendBody(BaseModel):
    symbols: List[str]
    weights: Dict[str, float]
    method: str = "rank"
    interval: str = "1d"
    period: str = "2y"
    n_quantiles: int = 5
    long_only: bool = True
    initial_capital: float = 100000.0


@router.get("/factors")
async def factors_registry(current_user: dict = Depends(get_current_user)):
    """Factor registry (name/family/category/description) + count."""
    return {"count": count_factors(), "factors": list_factors()}


async def _fetch_panel(symbols: List[str], interval: str, period: str, factors: List[str] | None) -> dict:
    histories: Dict[str, dict] = {}
    failures: List[str] = []
    for symbol in symbols:
        try:
            history = await market_data.get_history_auto(symbol, interval=interval, period=period)
            history = sanitize_history(history)
            if history.get("candles"):
                histories[symbol] = history
            else:
                failures.append(f"{symbol} (no data)")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{symbol} ({type(exc).__name__})")
    try:
        panel = build_panel(histories, factors)
    except (KeyError, ValueError, TypeError) as exc:
        failures.append(f"panel build failed: {exc}")
        panel = pd.DataFrame()
    return {"histories": histories, "panel": panel, "failures": failures}


@router.post("/factors/analysis")
async def factors_analysis(body: FactorAnalysisBody, current_user: dict = Depends(get_current_user)):
    """Per-factor rank IC / ICIR and quantile returns over a symbol panel."""
    if not body.symbols:
        raise HTTPException(status_code=422, detail="at least one symbol required")
    if body.forward_days < 1 or body.forward_days > 60:
        raise HTTPException(status_code=422, detail="forward_days must be in [1, 60]")
    fetched = await _fetch_panel(body.symbols, body.interval, body.period, body.factors)
    panel = fetched["panel"]
    if panel.empty:
        raise HTTPException(
            status_code=422,
            detail=f"no usable data for panel ({', '.join(fetched['failures']) or 'empty symbols'})",
        )
    factors = body.factors or [c for c in panel.columns if c.startswith("alpha101_")]
    unknown = [f for f in factors if f not in panel.columns]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown factor(s): {', '.join(unknown)}")
    ic = ic_analysis(panel, factors, body.forward_days)
    qr = quantile_returns(panel, factors, body.n_quantiles, body.forward_days)
    return {
        "symbols": list(fetched["histories"].keys()),
        "failures": fetched["failures"],
        "interval": body.interval,
        "forward_days": body.forward_days,
        "n_quantiles": body.n_quantiles,
        "ic": ic["factors"],
        "quantiles": qr["factors"],
    }


@router.post("/factors/bench")
async def factors_bench(body: FactorAnalysisBody, current_user: dict = Depends(get_current_user)):
    """Long-short factor bench (top vs bottom quantile, equal weight, daily
    rebalanced) for a single factor over a symbol panel."""
    if not body.symbols:
        raise HTTPException(status_code=422, detail="at least one symbol required")
    if not body.factors or len(body.factors) != 1:
        raise HTTPException(status_code=422, detail="exactly one factor required for a bench")
    fetched = await _fetch_panel(body.symbols, body.interval, body.period, body.factors)
    panel = fetched["panel"]
    if panel.empty:
        raise HTTPException(status_code=422, detail="no usable data for panel")
    result = factor_bench(panel, body.factors[0], body.n_quantiles, body.forward_days)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return {"symbols": list(fetched["histories"].keys()), "failures": fetched["failures"], **result}


@router.post("/signals/blend")
async def signals_blend(body: SignalBlendBody, current_user: dict = Depends(get_current_user)):
    """Blend factor signals into a weighted cross-sectional composite and run a
    top-quantile (or long-short) portfolio backtest over it."""
    if not body.symbols:
        raise HTTPException(status_code=422, detail="at least one symbol required")
    if not body.weights:
        raise HTTPException(status_code=422, detail="at least one factor weight required")
    if body.method not in ("rank", "zscore"):
        raise HTTPException(status_code=422, detail="method must be 'rank' or 'zscore'")
    if body.n_quantiles < 2 or body.n_quantiles > 20:
        raise HTTPException(status_code=422, detail="n_quantiles must be in [2, 20]")
    fetched = await _fetch_panel(body.symbols, body.interval, body.period, list(body.weights))
    panel = fetched["panel"]
    if panel.empty:
        raise HTTPException(status_code=422, detail="no usable data for panel")
    try:
        signal = composite_signal(panel, body.weights, body.method)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    signal.name = "composite"
    panel["composite"] = signal
    result = factor_portfolio_backtest(
        panel, "composite",
        n_quantiles=body.n_quantiles,
        initial_capital=body.initial_capital,
        interval=body.interval,
        long_only=body.long_only,
    )
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    result["weights"] = body.weights
    result["method"] = body.method
    result["symbols"] = list(fetched["histories"].keys())
    result["failures"] = fetched["failures"]
    return result
