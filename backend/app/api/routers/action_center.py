"""Action Center routes: human approval for pending orders."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import OrderSubmitRequest
from app.db.models import ActionCenterItem
from app.db.session import SessionFactory, get_session
from app.brokers.paper import PaperBroker
from app.brokers.interface import BrokerSide, ProductType, OrderType
from decimal import Decimal

router = APIRouter(prefix="/action-center", tags=["action-center"])


@router.get("")
async def list_items(
    status_filter: Optional[str] = None,
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    stmt = select(ActionCenterItem).where(ActionCenterItem.user_id == user.id)
    if status_filter:
        stmt = stmt.where(ActionCenterItem.status == status_filter)
    stmt = stmt.order_by(ActionCenterItem.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "side": r.side,
            "quantity": r.quantity,
            "price": r.price,
            "status": r.status,
            "order_type": r.order_type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "decision_note": r.decision_note,
        }
        for r in rows
    ]


@router.post("/{item_id}/approve")
async def approve(
    item_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Any:
    item = await session.scalar(
        select(ActionCenterItem).where(ActionCenterItem.id == item_id, ActionCenterItem.user_id == user.id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action center item not found")
    if item.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Item is {item.status}")
    from datetime import datetime
    item.status = "approved"
    item.decided_at = datetime.utcnow()
    await session.commit()
    return {"id": item.id, "status": item.status}


@router.post("/{item_id}/reject")
async def reject(
    item_id: str,
    note: str = "",
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    item = await session.scalar(
        select(ActionCenterItem).where(ActionCenterItem.id == item_id, ActionCenterItem.user_id == user.id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action center item not found")
    if item.status != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Item is {item.status}")
    from datetime import datetime
    item.status = "rejected"
    item.decision_note = note
    item.decided_at = datetime.utcnow()
    await session.commit()
    return {"id": item.id, "status": item.status}


@router.post("/{item_id}/execute")
async def execute_item(
    item_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Any:
    item = await session.scalar(
        select(ActionCenterItem).where(ActionCenterItem.id == item_id, ActionCenterItem.user_id == user.id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action center item not found")
    if item.status != "approved":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Item is {item.status}, must be approved")

    broker = PaperBroker(user_id=user.id)
    side = BrokerSide(item.side)
    product = ProductType.CNC
    order_type = OrderType(item.order_type or "MARKET")
    result = await broker.place_order(
        symbol=item.symbol,
        side=side,
        product=product,
        order_type=order_type,
        quantity=Decimal(item.quantity),
        price=Decimal(str(item.price)) if item.price else None,
    )
    if result.status in ("rejected", "cancelled"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.error_message or "Execution failed")

    # Persist order
    async with SessionFactory() as s2:
        from sqlalchemy import insert
        from app.db.models import Order as OrderModel
        await s2.execute(
            insert(OrderModel).values(
                user_id=user.id,
                symbol=item.symbol,
                side=item.side,
                quantity=item.quantity,
                price=float(result.filled_price or item.price or 0),
                status="filled",
                order_type=item.order_type or "MARKET",
                extra_data=result.order_id,
            )
        )
        await s2.commit()

    from datetime import datetime
    item.status = "executed"
    item.decided_at = datetime.utcnow()
    await session.commit()
    return {"id": item.id, "status": item.status, "order_id": result.order_id}
