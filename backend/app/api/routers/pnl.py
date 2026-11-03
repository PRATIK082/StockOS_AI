"""PnL routes (Phase 9b): realized/unrealized summary + equity curve."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_session
from app.services import pnl as pnl_svc

router = APIRouter(prefix="/pnl", tags=["pnl"])

RangeStr = Literal["7d", "30d", "90d", "1y", "all"]


@router.get("/summary")
async def summary(
    range: RangeStr = Query("all"),
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Realized (FIFO) + unrealized + totals for the range."""
    window = pnl_svc.RANGE_WINDOWS[range]
    since = datetime.utcnow() - window if window else None
    fills = await pnl_svc.filled_orders(user.id, session, since)
    realized = pnl_svc.fifo_realized(
        [{"symbol": o.symbol, "side": o.side, "quantity": o.quantity, "price": o.price}
         for o in fills]
    )
    un = await pnl_svc.unrealized(user.id, session)
    total = realized["total"] + un["total"]
    return {
        "range": range,
        "fills": len(fills),
        "realized": realized,
        "unrealized": un,
        "total_pnl": round(total, 2),
    }


@router.get("/equity")
async def equity(
    range: RangeStr = Query("30d"),
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Step curve of cumulative realized PnL at fill timestamps.

    Historical unrealized is not captured in v1; the final point is the live
    snapshot (realized + current unrealized) flagged ``live: true``.
    """
    window = pnl_svc.RANGE_WINDOWS[range]
    since = datetime.utcnow() - window if window else None
    fills = await pnl_svc.filled_orders(user.id, session, since)
    points: list[dict[str, Any]] = []
    running: list[dict[str, Any]] = []
    cumulative = Decimal("0")
    for o in fills:
        running.append({"symbol": o.symbol, "side": o.side,
                        "quantity": o.quantity, "price": o.price})
        step = pnl_svc.fifo_realized(running)
        cumulative = Decimal(str(step["total"]))
        if str(o.side).upper() == "SELL":
            points.append({"t": o.created_at.isoformat(), "realized": float(cumulative)})
    un = await pnl_svc.unrealized(user.id, session)
    points.append({
        "t": datetime.utcnow().isoformat(),
        "realized": float(cumulative),
        "unrealized": un["total"],
        "total": round(float(cumulative) + un["total"], 2),
        "live": True,
    })
    return {"range": range, "points": points,
            "note": "Historical unrealized is not captured in v1; only the live point includes it."}
