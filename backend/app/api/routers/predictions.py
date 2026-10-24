"""Per-user prediction history routes (save / list / delete)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import PredictionHistoryCreate
from app.db.models import PredictionHistory
from app.db.session import get_session

router = APIRouter(prefix="/predictions", tags=["predictions"])


def _to_dict(row: PredictionHistory) -> dict:
    try:
        payload = json.loads(row.payload or "{}")
    except (ValueError, TypeError):
        payload = {}
    return {
        "id": row.id,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "payload": payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
async def list_predictions(user: CurrentUser, session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (
        await session.scalars(
            select(PredictionHistory)
            .where(PredictionHistory.user_id == user.id)
            .order_by(PredictionHistory.created_at.desc())
            .limit(200)
        )
    ).all()
    return [_to_dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def save_prediction(
    body: PredictionHistoryCreate, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    row = PredictionHistory(
        user_id=user.id,
        symbol=body.symbol,
        timeframe=body.timeframe or "1W",
        payload=json.dumps(body.payload),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


@router.delete("/{prediction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prediction(
    prediction_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> None:
    row = await session.scalar(
        select(PredictionHistory).where(
            PredictionHistory.id == prediction_id, PredictionHistory.user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prediction not found")
    await session.delete(row)
    await session.commit()
