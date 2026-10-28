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
from app.brokers.factory import get_broker
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

    from app.core.config import get_settings

    broker = get_broker(name=getattr(get_settings(), "selected_execution_broker", None), user_id=user.id)
    import json as _json
    from app.services.order_workflows import parse_approval_payload
    spec = parse_approval_payload(item)
    kind = str(spec.get("kind") or item.order_type or "MARKET").lower()
    # normalize kind names
    if kind in ("smart_order", "smartorder"):
        kind = "smart"
    if kind in ("basket_order", "basketorder", "placebasketorder"):
        kind = "basket"
    if kind in ("split_order", "splitorder"):
        kind = "split"

    results = []
    if kind == "smart":
        fields = spec.get("fields", {}) if isinstance(spec.get("fields"), dict) else {}
        if not fields:
            fields = {"symbol": item.symbol, "side": item.side, "quantity": item.quantity, "price": item.price, "order_type": item.order_type or "MARKET"}
        from app.services.order_workflows import smart_order as run_smart
        results = await run_smart(
            broker,
            symbol=fields.get("symbol", item.symbol),
            side=fields.get("side", item.side),
            quantity=fields.get("quantity", item.quantity),
            price=fields.get("price", item.price),
            order_type=fields.get("order_type", item.order_type or "MARKET"),
            chase=bool(fields.get("chase", False)),
            position_size=fields.get("position_size", None),
            stop_loss=fields.get("stop_loss", None),
            target=fields.get("target", None),
        )
    elif kind == "basket":
        orders = spec.get("orders", [])
        if not orders:
            try:
                orders = _json.loads(item.payload or "{}").get("orders", [])
            except Exception:
                orders = []
        from app.services.order_workflows import basket_order as run_basket
        results = await run_basket(broker, orders)
    elif kind == "split":
        fields = spec.get("fields", {}) if isinstance(spec.get("fields"), dict) else {}
        if not fields:
            fields = {"symbol": item.symbol, "side": item.side, "quantity": item.quantity, "price": item.price, "order_type": item.order_type or "MARKET"}
        splits = spec.get("splits", None)
        split_size = spec.get("split_size", None)
        from app.services.order_workflows import split_order as run_split
        results = await run_split(
            broker,
            symbol=fields.get("symbol", item.symbol),
            side=fields.get("side", item.side),
            quantity=fields.get("quantity", item.quantity),
            splits=splits,
            split_size=split_size,
            price=fields.get("price", item.price),
            order_type=fields.get("order_type", item.order_type or "MARKET"),
            chase=bool(fields.get("chase", False)),
        )
    else:
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
        results = [result]

    if not results:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No orders executed")
    for r in results:
        if getattr(r, "status", None) in ("rejected", "cancelled"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, getattr(r, "error_message", None) or "Execution failed")

    # Persist orders
    async with SessionFactory() as s2:
        from sqlalchemy import insert
        from app.db.models import Order as OrderModel
        for r in results:
            await s2.execute(
                insert(OrderModel).values(
                    user_id=user.id,
                    symbol=getattr(r, "symbol", item.symbol),
                    side=getattr(r, "side", item.side),
                    quantity=str(getattr(r, "quantity", item.quantity)),
                    price=float(getattr(r, "filled_price", None) or item.price or 0),
                    status="filled",
                    order_type=item.order_type or "MARKET",
                    extra_data=getattr(r, "order_id", None),
                )
            )
        await s2.commit()

    from datetime import datetime
    item.status = "executed"
    item.decided_at = datetime.utcnow()
    await session.commit()
    return {"id": item.id, "status": item.status, "order_id": getattr(results[0], "order_id", None), "order_ids": [getattr(r, "order_id", None) for r in results]}
