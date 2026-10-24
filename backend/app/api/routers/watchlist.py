"""Watchlist routes (per-user)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import WatchlistCreate, WatchlistUpdate
from app.db.models import Watchlist
from app.db.session import get_session

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _split(symbols: str) -> list[str]:
    return [s for s in symbols.split(",") if s.strip()]


@router.get("")
async def list_watchlists(user: CurrentUser, session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.scalars(select(Watchlist).where(Watchlist.user_id == user.id))).all()
    return [
        {"id": w.id, "name": w.name, "symbols": _split(w.symbols)} for w in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    body: WatchlistCreate, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    wl = Watchlist(user_id=user.id, name=body.name)
    session.add(wl)
    await session.commit()
    await session.refresh(wl)
    return {"id": wl.id, "name": wl.name, "symbols": []}


@router.patch("/{watchlist_id}/symbols")
async def update_symbols(
    watchlist_id: str,
    body: WatchlistUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict:
    wl = await session.scalar(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id)
    )
    if wl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watchlist not found")

    symbols = _split(wl.symbols)
    if body.action == "add" and body.symbol not in symbols:
        symbols.append(body.symbol)
    elif body.action == "remove" and body.symbol in symbols:
        symbols.remove(body.symbol)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No change or unknown action")

    wl.symbols = ", ".join(symbols)
    await session.commit()
    return {"id": wl.id, "name": wl.name, "symbols": symbols}