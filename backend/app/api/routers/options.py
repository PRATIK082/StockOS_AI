"""Tracked option position routes (per-user PUT/CALL paper positions)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import OptionPositionCreate
from app.db.models import OptionPosition
from app.db.session import get_session

router = APIRouter(prefix="/options", tags=["options"])


def _normalize(option_type: str) -> str:
    t = option_type.upper()
    if t == "CE":
        return "CALL"
    if t == "PE":
        return "PUT"
    return t


def _to_dict(row: OptionPosition) -> dict:
    expiry = row.expiry
    return {
        "id": row.id,
        "symbol": row.symbol,
        "option_type": row.option_type,
        "strike": float(row.strike or 0),
        "expiry": expiry.isoformat() if isinstance(expiry, (date, datetime)) else str(expiry),
        "quantity": float(row.quantity or 0),
        "premium": float(row.premium or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/positions")
async def list_positions(user: CurrentUser, session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (
        await session.scalars(
            select(OptionPosition).where(OptionPosition.user_id == user.id).order_by(OptionPosition.created_at.desc())
        )
    ).all()
    return [_to_dict(r) for r in rows]


@router.post("/positions", status_code=status.HTTP_201_CREATED)
async def add_position(
    body: OptionPositionCreate, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        expiry = date.fromisoformat(body.expiry[:10])
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "expiry must be an ISO date (YYYY-MM-DD)")

    row = OptionPosition(
        user_id=user.id,
        symbol=body.symbol.upper(),
        option_type=_normalize(body.option_type),
        strike=str(body.strike),
        expiry=expiry,
        quantity=str(body.quantity),
        premium=str(body.premium),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(
    position_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> None:
    row = await session.scalar(
        select(OptionPosition).where(OptionPosition.id == position_id, OptionPosition.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Option position not found")
    await session.delete(row)
    await session.commit()
