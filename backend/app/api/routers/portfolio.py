"""Portfolio routes (per-user holdings with live PnL)."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import HoldingCreate
from app.db.models import Holding
from app.db.session import get_session
from app.services.data.service import market_data

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("")
async def holdings(user: CurrentUser, session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.scalars(select(Holding).where(Holding.user_id == user.id))).all()

    enriched = []
    total_cost = Decimal("0")
    total_value = Decimal("0")
    for h in rows:
        qty = Decimal(h.quantity or "0")
        cost = Decimal(h.average_cost or "0")
        try:
            quote = await market_data.get_quote(h.symbol)
            price = Decimal(str(quote.get("price") or 0))
        except Exception:  # noqa: BLE001
            price = Decimal("0")
        value = qty * price
        invested = qty * cost
        total_cost += invested
        total_value += value
        enriched.append(
            {
                "id": h.id,
                "symbol": h.symbol,
                "quantity": str(qty),
                "average_cost": str(cost),
                "current_price": float(price),
                "invested": float(invested),
                "value": float(value),
                "pnl": float(value - invested),
                "pnl_pct": float(((value - invested) / invested * 100)) if invested else 0.0,
            }
        )

    return {
        "holdings": enriched,
        "summary": {
            "invested": float(total_cost),
            "value": float(total_value),
            "pnl": float(total_value - total_cost),
            "pnl_pct": float((total_value - total_cost) / total_cost * 100) if total_cost else 0.0,
        },
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_holding(
    body: HoldingCreate, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    existing = await session.scalar(
        select(Holding).where(Holding.user_id == user.id, Holding.symbol == body.symbol.upper())
    )
    if existing is None:
        existing = Holding(user_id=user.id, symbol=body.symbol.upper())
        session.add(existing)

    # Quantity-weighted average cost update.
    old_qty = Decimal(existing.quantity or "0")
    old_cost = Decimal(existing.average_cost or "0")
    new_qty = Decimal(body.quantity)
    new_cost = Decimal(body.average_cost)
    total_qty = old_qty + new_qty
    if total_qty > 0:
        existing.average_cost = str((old_qty * old_cost + new_qty * new_cost) / total_qty)
    existing.quantity = str(total_qty)

    await session.commit()
    await session.refresh(existing)
    return {"id": existing.id, "symbol": existing.symbol, "quantity": existing.quantity}


@router.delete("/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(
    holding_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> None:
    row = await session.scalar(
        select(Holding).where(Holding.id == holding_id, Holding.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holding not found")
    await session.delete(row)
    await session.commit()