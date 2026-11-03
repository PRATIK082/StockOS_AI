"""Market calendar routes (Phase 9d): holidays, timings, live status."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_role
from app.db.models.calendar import MarketHoliday
from app.db.models.user import User
from app.db.session import get_session
from app.services import market_calendar as cal

router = APIRouter(prefix="/calendar", tags=["calendar"])

AdminUser = Annotated[User, Depends(require_role("admin"))]


class HolidayIn(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=128)


@router.get("/holidays")
async def holidays(
    year: int = Query(default_factory=lambda: date.today().year, ge=2000, le=2100),
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Merged seed + admin holidays for ``year`` (admin rows win)."""
    return {"year": year, "holidays": await cal.get_holidays(year, session)}


@router.post("/holidays", status_code=201)
async def add_holiday(
    body: HolidayIn,
    user: AdminUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Add or override a holiday (admin). Restores a removed seed date too."""
    existing = (
        await session.execute(select(MarketHoliday).where(MarketHoliday.date == body.date))
    ).scalar_one_or_none()
    if existing:
        existing.name = body.name.strip()
        existing.removed = False
    else:
        session.add(MarketHoliday(date=body.date, name=body.name.strip(), removed=False))
    await session.commit()
    return {"date": body.date.isoformat(), "name": body.name.strip(), "source": "admin"}


@router.delete("/holidays/{day}")
async def delete_holiday(
    day: date,
    user: AdminUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Remove an admin holiday, or hide a seed date via tombstone (admin)."""
    existing = (
        await session.execute(select(MarketHoliday).where(MarketHoliday.date == day))
    ).scalar_one_or_none()
    if existing and not existing.removed:
        # Admin-added row: delete it outright unless it shadows a seed date.
        seed_dates = {row["date"] for row in cal.load_seed_holidays()}
        if day.isoformat() in seed_dates:
            existing.removed = True
            existing.name = existing.name
        else:
            await session.delete(existing)
    elif not existing:
        seed_dates = {row["date"] for row in cal.load_seed_holidays()}
        if day.isoformat() not in seed_dates:
            raise HTTPException(404, "Holiday not found")
        session.add(MarketHoliday(date=day, name="", removed=True))
    await session.commit()
    return {"date": day.isoformat(), "deleted": True}


@router.get("/timings")
async def get_timings(user: CurrentUser = None) -> Any:
    """Static NSE equity session timings (IST)."""
    return cal.timings()


@router.get("/status")
async def status(
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Live market open/closed status with session + next trading day."""
    now = datetime.utcnow()
    lookup = await cal.holiday_lookup(session, date(2000, 1, 1), date(2100, 1, 1))
    payload = cal.get_status(now, lookup)
    today_ist = (now + cal.IST_OFFSET).date()
    nxt = cal.next_trading_day(today_ist, lookup)
    payload["next_trading_day"] = nxt.isoformat() if nxt else None
    return payload
