"""Order management routes: preview, submit, cancel, kill-switch, square-off."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import OrderPreviewRequest, OrderSubmitRequest, OrderResponse
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Order as OrderModel
from app.db.session import SessionFactory, get_session
from app.brokers.paper import PaperBroker
from app.brokers.interface import BrokerSide, ProductType, OrderType
from app.services.data.providers import parse_symbol

router = APIRouter(prefix="/v1/orders", tags=["orders"])

logger = get_logger("orders.router")


# ---- helpers -----------------------------------------------------------

def _get_broker(user_id: str) -> PaperBroker:
    """Return the active broker for the user (paper by default)."""
    return PaperBroker(user_id=user_id)


def _qty_to_int(q: Any) -> int:
    """Convert a quantity (float/str/int) to an int safely."""
    try:
        return int(float(q))
    except (TypeError, ValueError):
        return 0


# ---- routes ------------------------------------------------------------

@router.post("/preview", response_model=OrderResponse, status_code=status.HTTP_200_OK)
async def order_preview(
    body: OrderPreviewRequest, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    """Preview an order: validate symbols, check risk, estimate simulated fill."""
    from app.services.risk.risk_engine import RiskEngine

    symbol = (body.symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "symbol is required"
        )

    try:
        parse_symbol(symbol)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid symbol '{symbol}': {exc}"
        ) from exc

    # Get a quote for preview
    broker = _get_broker(user.id)
    try:
        quote = await broker.quote(symbol)
        price = float(quote.last_price)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Could not fetch quote for '{symbol}': {exc}",
        ) from exc

    if price <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"No price data for '{symbol}'"
        )

    # Basic risk checks
    risk_ok, risk_notes = RiskEngine.check_order(
        symbol=symbol,
        quantity=body.quantity,
        side=body.side,
        entry_price=Decimal(str(price)),
    )

    if not risk_ok:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Risk check failed: {risk_notes}",
        )

    estimated_fill = price

    return OrderResponse(
        id=f"preview-{uuid.uuid4().hex[:8]}",
        symbol=symbol,
        side=body.side,
        quantity=int(body.quantity),
        price=price,
        estimated_fill=estimated_fill,
        status="preview",
        risk_notes={"message": risk_notes} if risk_notes else None,
    )


@router.post("/submit", status_code=status.HTTP_201_CREATED)
async def order_submit(
    body: OrderSubmitRequest, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    """Submit an order to the broker (paper or live)."""
    symbol = (body.symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "symbol is required"
        )

    try:
        parse_symbol(symbol)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid symbol '{symbol}': {exc}"
        ) from exc

    broker = _get_broker(user.id)

    # Risk check before submission
    try:
        quote = await broker.quote(symbol)
        price_for_risk = float(quote.last_price)
    except Exception:
        price_for_risk = float(body.price) if body.price else 0.0
    if price_for_risk > 0:
        from app.services.risk.risk_engine import RiskEngine
        from decimal import Decimal
        risk_ok, risk_notes = RiskEngine.check_order(
            symbol=symbol,
            quantity=Decimal(str(body.quantity)),
            side=body.side,
            entry_price=Decimal(str(price_for_risk)),
        )
        if not risk_ok:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Risk check failed: {risk_notes}",
            )

    # Determine side, product, order_type
    side = BrokerSide(body.side)
    product = ProductType.CNC
    order_type = OrderType(body.order_type or "MARKET")

    result = await broker.place_order(
        symbol=symbol,
        side=side,
        product=product,
        order_type=order_type,
        quantity=Decimal(str(body.quantity)),
        price=Decimal(str(body.price)) if body.price else None,
    )

    if result.status in ("rejected", "cancelled"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            result.error_message or "Order submission failed",
        )

    # Persist the order record
    db_order_id = None
    async with SessionFactory() as session2:
        from sqlalchemy import insert

        row = await session2.execute(
            insert(OrderModel)
            .values(
                user_id=user.id,
                symbol=symbol,
                side=body.side,
                quantity=str(body.quantity),
                price=float(result.filled_price or body.price or 0),
                status="filled",
                order_type=body.order_type or "MARKET",
                extra_data=result.order_id,  # store paper broker ID for cross-reference
            )
            .returning(OrderModel.id)
        )
        db_order_id = row.scalar_one()
        await session2.commit()

    return {
        "id": db_order_id,
        "order_id": result.order_id,
        "symbol": symbol,
        "side": body.side,
        "quantity": body.quantity,
        "fill_price": float(result.filled_price) if result.filled_price else None,
        "status": "filled",
        "message": "Order submitted (paper mode)",
    }


@router.post("/kill-switch", status_code=status.HTTP_200_OK)
async def order_kill_switch(
    user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    """Emergency stop: cancel all open orders + square off all positions."""
    broker = _get_broker(user.id)

    # Square off all open positions
    kill_result = await broker.kill_switch()

    # Persist the emergency event
    async with SessionFactory() as session2:
        from sqlalchemy import insert

        await session2.execute(
            insert(OrderModel).values(
                user_id=user.id,
                symbol="EMERGENCY",
                side="hold",
                quantity="0",
                price=0,
                status="cancelled",
                order_type="MARKET",
                extra_data=f"kill-switch:{kill_result.get('active', False)}",
            )
        )
        await session2.commit()

    return {
        "message": "Kill switch executed",
        "positions_square_off": kill_result,
    }


@router.post("/cancel-all", status_code=status.HTTP_200_OK)
async def order_cancel_all(
    user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    """Cancel all open orders."""
    broker = _get_broker(user.id)
    if hasattr(broker, "cancel_all_orders"):
        result = await broker.cancel_all_orders()
    else:
        result = await broker.kill_switch()

    return {"orders_cancelled": result}


@router.post("/square-off", status_code=status.HTTP_200_OK)
async def order_square_off(
    user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    """Close all open positions (square off)."""
    broker = _get_broker(user.id)
    result = await broker.square_off()

    return {"positions_closed": result}


@router.get("", response_model=list[OrderResponse], status_code=status.HTTP_200_OK)
async def order_list(
    user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    """List order history for the current user."""
    result = await session.execute(
        select(OrderModel).where(OrderModel.user_id == user.id).order_by(OrderModel.created_at.desc())
    )
    rows = result.scalars().all()
    return [
        OrderResponse(
            id=str(row.id),
            symbol=row.symbol,
            side=row.side,
            quantity=_qty_to_int(row.quantity),
            price=float(row.price or 0),
            status=row.status,
            estimated_fill=None,
            risk_notes=None,
        )
        for row in rows
    ]


@router.get("/{order_id}", response_model=OrderResponse, status_code=status.HTTP_200_OK)
async def order_detail(
    order_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    """Get a single order by ID (supports both DB UUID and broker order ID)."""
    from sqlalchemy import or_

    row = await session.scalar(
        select(OrderModel).where(
            OrderModel.user_id == user.id,
            or_(OrderModel.id == order_id, OrderModel.extra_data == order_id),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")

    return OrderResponse(
        id=str(row.id),
        symbol=row.symbol,
        side=row.side,
        quantity=_qty_to_int(row.quantity),
        price=float(row.price or 0),
        status=row.status,
        estimated_fill=None,
        risk_notes=None,
    )
