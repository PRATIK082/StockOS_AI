"""Chart markup / annotation routes."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import CurrentUser
from app.services.agents.chart_markup import chart_markup_service

router = APIRouter(prefix="/chart-markup", tags=["chart-markup"])


@router.get("")
async def get_chart_markup(
    symbol: str = Query(...),
    interval: str = Query("1d"),
    period: str = Query("3mo"),
    provider: Optional[str] = Query(None),
    user: CurrentUser = None,
) -> dict[str, Any]:
    try:
        return await chart_markup_service.build(symbol, interval=interval, period=period, provider=provider)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Chart markup failed: {exc}") from exc
