"""Market data routes: quote, history, fundamentals, providers, health."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import FundamentalsResponse, HistoryResponse, QuoteResponse
from app.services.data.providers import parse_symbol
from app.services.data.service import PROVIDERS, market_data

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/providers")
async def providers() -> dict:
    return {
        name: {"name": prov.name, "display_name": prov.display_name}
        for name, prov in PROVIDERS.items()
    }


@router.get("/quote/{symbol:path}", response_model=QuoteResponse)
async def quote(symbol: str, provider: str | None = None) -> dict:
    _validate_symbol(symbol)
    try:
        return await market_data.get_quote(symbol, provider=provider)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Data provider failed: {exc}") from exc


@router.get("/history/{symbol:path}", response_model=HistoryResponse)
async def history(
    symbol: str,
    interval: str = Query("1d", pattern="^(1m|5m|15m|1h|1d|1wk|1mo)$"),
    period: str = Query("1y", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y|max)$"),
    provider: str | None = None,
    source: str | None = Query(None, description="'auto' walks the per-market fallback chain"),
) -> dict:
    _validate_symbol(symbol)
    try:
        if source == "auto" and provider is None:
            return await market_data.get_history_auto(symbol, interval=interval, period=period)
        return await market_data.get_history(symbol, interval=interval, period=period, provider=provider)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Data provider failed: {exc}") from exc


@router.get("/fundamentals/{symbol:path}", response_model=FundamentalsResponse)
async def fundamentals(symbol: str, provider: str | None = None) -> dict:
    _validate_symbol(symbol)
    try:
        return await market_data.get_fundamentals(symbol, provider=provider)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Data provider failed: {exc}") from exc


@router.get("/health")
async def health() -> dict:
    return await market_data.health()


@router.get("/status")
async def provider_status() -> dict:
    """Per-provider reachability + capability metadata (see service.provider_status)."""
    return await market_data.provider_status()


@router.get("/sources")
async def sources_status() -> dict:
    """Loader health + per-market fallback chains readout (honest live probe)."""
    return await market_data.sources_status()


def _validate_symbol(symbol: str) -> None:
    try:
        parse_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
