"""Options analytics + margin routes (Phase 6).

All analytics run over the **real** option chain supplied by the market-data
provider.  When the provider cannot supply a chain the routes return 404 with a
clear message instead of fabricating numbers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.services.data.providers.base import OptionsUnavailableError
from app.services.data.service import market_data
from app.services.options import analytics as opt_analytics
from app.services.options.margin import calculate_margin, synthetic_futures

analytics_router = APIRouter(prefix="/options/analytics", tags=["options-analytics"])
margin_router = APIRouter(prefix="/options/margin", tags=["options-margin"])


# --------------------------------------------------------------------------- helpers

async def _load_chain(
    symbol: str, expiry: Optional[str] = None
) -> opt_analytics.NormalizedChain:
    """Fetch and normalise the option chain for ``symbol``."""
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "symbol is required")
    try:
        raw = await market_data.get_option_chain(symbol, expiry=expiry)
    except OptionsUnavailableError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Options chain failed for {symbol}: {exc}"
        ) from exc
    if not raw:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No options chain for {symbol}")
    chain = opt_analytics.normalize_chain(raw, symbol)
    if not chain.calls and not chain.puts:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Options chain for {symbol} contains no contracts"
        )
    return chain


# --------------------------------------------------------------------------- max pain

@analytics_router.get("/max-pain")
async def max_pain(
    symbol: str = Query(..., description="Underlying symbol, e.g. NIFTY"),
    expiry: Optional[str] = Query(None, description="Expiry date (YYYY-MM-DD)"),
    user: CurrentUser = None,
) -> Dict[str, Any]:
    """Strike where option writers' payout is minimal."""
    chain = await _load_chain(symbol, expiry)
    strike = opt_analytics.max_pain(chain)
    return {
        "symbol": chain.symbol,
        "expiry": chain.expiry,
        "spot": chain.spot,
        "max_pain": strike,
        "available": strike is not None,
        "note": None if strike is not None else "Provider does not publish open interest.",
    }


# --------------------------------------------------------------------------- OI

@analytics_router.get("/oi-profile")
async def oi_profile(
    symbol: str = Query(...),
    expiry: Optional[str] = Query(None),
    user: CurrentUser = None,
) -> Dict[str, Any]:
    """Open interest distribution by strike plus put/call ratio."""
    chain = await _load_chain(symbol, expiry)
    return opt_analytics.oi_profile(chain)


@analytics_router.get("/oi-change")
async def oi_change(
    symbol: str = Query(...),
    expiry: Optional[str] = Query(None),
    user: CurrentUser = None,
) -> Dict[str, Any]:
    """Intraday open-interest change by strike (when the provider publishes it)."""
    chain = await _load_chain(symbol, expiry)
    return opt_analytics.oi_change_profile(chain)


# --------------------------------------------------------------------------- volatility

@analytics_router.get("/iv-smile")
async def iv_smile(
    symbol: str = Query(...),
    expiry: Optional[str] = Query(None),
    user: CurrentUser = None,
) -> Dict[str, Any]:
    """Implied-volatility smile, ATM IV and 25-delta skew for one expiry."""
    chain = await _load_chain(symbol, expiry)
    return opt_analytics.iv_smile(chain)


@analytics_router.get("/vol-surface")
async def vol_surface(
    symbol: str = Query(...),
    expiries: Optional[str] = Query(None, description="Comma separated expiry dates"),
    max_expiries: int = Query(4, ge=1, le=12),
    user: CurrentUser = None,
) -> Dict[str, Any]:
    """IV surface (strike x expiry matrix) and the ATM term structure."""
    symbol = symbol.strip().upper()
    wanted: List[str] = []
    if expiries:
        wanted = [e.strip()[:10] for e in expiries.split(",") if e.strip()]

    chains: List[opt_analytics.NormalizedChain] = []
    if wanted:
        for exp in wanted[:max_expiries]:
            try:
                raw = await market_data.get_option_chain(symbol, expiry=exp)
            except OptionsUnavailableError:
                continue
            except Exception:  # noqa: BLE001
                continue
            if raw:
                chains.append(opt_analytics.normalize_chain(raw, symbol))
    else:
        first = await _load_chain(symbol, None)
        candidates = [e for e in first.expiries if e]
        if not candidates:
            candidates = [first.expiry] if first.expiry else []
        for exp in candidates[:max_expiries]:
            if exp == first.expiry:
                chains.append(first)
                continue
            try:
                raw = await market_data.get_option_chain(symbol, expiry=exp)
            except OptionsUnavailableError:
                continue
            except Exception:  # noqa: BLE001
                continue
            if raw:
                chains.append(opt_analytics.normalize_chain(raw, symbol))

    if not chains:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No option chains available for {symbol}")
    return opt_analytics.vol_surface(chains)


# --------------------------------------------------------------------------- GEX

@analytics_router.get("/gex")
async def gamma_exposure(
    symbol: str = Query(...),
    expiry: Optional[str] = Query(None),
    user: CurrentUser = None,
) -> Dict[str, Any]:
    """Gamma exposure by strike, zero-gamma strike and flip point."""
    chain = await _load_chain(symbol, expiry)
    return opt_analytics.gamma_exposure(chain)


# --------------------------------------------------------------------------- straddle

@analytics_router.get("/straddle")
async def straddle(
    symbol: str = Query(...),
    expiry: Optional[str] = Query(None),
    strike: Optional[float] = Query(None, description="Defaults to the ATM strike"),
    entry_premium: Optional[float] = Query(None, description="Defaults to live ATM call+put premium"),
    position: str = Query("long", pattern="^(long|short)$"),
    user: CurrentUser = None,
) -> Dict[str, Any]:
    """Straddle payoff curve, breakevens, max profit and max loss."""
    chain = await _load_chain(symbol, expiry)
    try:
        return opt_analytics.straddle_pnl(
            chain,
            strike=strike,
            entry_premium=entry_premium,
            position=position,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


# --------------------------------------------------------------------------- margin

class MarginRequest(BaseModel):
    symbol: str
    side: str = "BUY"
    quantity: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    segment: str = "equity"
    product: str = "MIS"
    lot_size: int = Field(1, ge=1)
    available_margin: Optional[float] = None


@margin_router.post("/calculate")
async def margin_calculate(body: MarginRequest, user: CurrentUser = None) -> Dict[str, Any]:
    """Estimate the margin required for an order."""
    try:
        result = calculate_margin(
            symbol=body.symbol,
            side=body.side,
            quantity=body.quantity,
            price=body.price,
            segment=body.segment,
            product=body.product,
            lot_size=body.lot_size,
            available_margin=body.available_margin,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return result.to_dict()


class SyntheticFuturesRequest(BaseModel):
    symbol: str
    direction: str = "long"
    strike: Optional[float] = Field(None, gt=0)
    quantity: float = Field(1, gt=0)
    lot_size: int = Field(1, ge=1)
    expiry: Optional[str] = None
    call_premium: Optional[float] = None
    put_premium: Optional[float] = None
    spot: Optional[float] = None


@margin_router.post("/synthetic-futures")
async def synthetic_futures_endpoint(
    body: SyntheticFuturesRequest, user: CurrentUser = None
) -> Dict[str, Any]:
    """Cost, breakeven and margin of a synthetic futures position.

    When premiums are not supplied they are read from the live option chain.
    """
    call_premium = body.call_premium
    put_premium = body.put_premium
    strike = body.strike
    spot = body.spot
    lot_size = body.lot_size

    if call_premium is None or put_premium is None or strike is None:
        chain = await _load_chain(body.symbol, body.expiry)
        spot = spot or chain.spot
        if strike is None:
            strike = chain.atm_strike()
        if strike is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "No strike available for the chain"
            )
        call_leg = chain.call_at(strike)
        put_leg = chain.put_at(strike)
        if call_premium is None:
            call_premium = call_leg.ltp if call_leg else 0.0
        if put_premium is None:
            put_premium = put_leg.ltp if put_leg else 0.0
        if not call_leg or not put_leg:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"No call/put pair at strike {strike} for {body.symbol}",
            )
        lot_size = call_leg.lot_size or put_leg.lot_size or lot_size

    try:
        result = synthetic_futures(
            symbol=body.symbol,
            direction=body.direction,
            strike=float(strike or 0),
            quantity=body.quantity,
            lot_size=lot_size,
            call_premium=float(call_premium or 0),
            put_premium=float(put_premium or 0),
            spot=float(spot or 0),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return result.to_dict()
