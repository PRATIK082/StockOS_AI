"""Market calendar service (Phase 9d).

Merges the hand-maintained NSE seed file with the admin ``market_holidays``
table (DB wins), and exposes trading-day + live-status helpers. All times are
IST (UTC+5:30, no DST). Pure date logic is kept free of DB access so it is
trivially testable; the router loads the holiday set and passes it in.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.market_session import MarketHours, get_current_session, is_trading_session

IST_OFFSET = timedelta(hours=5, minutes=30)

_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "nse_holidays.json"


@lru_cache(maxsize=1)
def load_seed_holidays() -> list[dict[str, Any]]:
    """Read the seed JSON file. Returns [{date, name, provisional}]."""
    try:
        raw = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for row in raw.get("holidays", []):
        try:
            datetime.strptime(row["date"], "%Y-%m-%d")
        except (KeyError, ValueError):
            continue
        out.append(
            {
                "date": row["date"],
                "name": str(row.get("name", "")),
                "provisional": bool(row.get("provisional", False)),
            }
        )
    return out


async def get_holidays(year: int, session: AsyncSession) -> list[dict[str, Any]]:
    """Merged seed + DB holidays for ``year``, sorted by date.

    DB rows override the seed on the same date; ``removed=True`` rows hide
    seed dates. ``source`` is ``admin`` or ``seed``.
    """
    from app.db.models.calendar import MarketHoliday

    merged: dict[str, dict[str, Any]] = {}
    for row in load_seed_holidays():
        if row["date"].startswith(str(year)):
            merged[row["date"]] = {**row, "source": "seed"}
    db_rows = (
        await session.execute(select(MarketHoliday).where(MarketHoliday.date >= date(year, 1, 1),
                                                          MarketHoliday.date <= date(year, 12, 31)))
    ).scalars().all()
    for row in db_rows:
        key = row.date.isoformat()
        if row.removed:
            merged.pop(key, None)
        else:
            merged[key] = {"date": key, "name": row.name, "provisional": False, "source": "admin"}
    return [merged[k] for k in sorted(merged)]


async def holiday_lookup(session: AsyncSession, start: date, end: date) -> dict[str, str]:
    """{iso-date: name} for every effective holiday in [start, end]."""
    from app.db.models.calendar import MarketHoliday

    lookup: dict[str, str] = {}
    for row in load_seed_holidays():
        if start.isoformat() <= row["date"] <= end.isoformat():
            lookup[row["date"]] = row["name"]
    db_rows = (
        await session.execute(
            select(MarketHoliday).where(MarketHoliday.date >= start, MarketHoliday.date <= end)
        )
    ).scalars().all()
    for row in db_rows:
        key = row.date.isoformat()
        if row.removed:
            lookup.pop(key, None)
        else:
            lookup[key] = row.name
    return lookup


def is_trading_day(day: date, holidays: dict[str, str] | set[str]) -> bool:
    """A trading day is Mon-Fri and not a holiday."""
    if day.weekday() >= 5:
        return False
    return day.isoformat() not in holidays


def next_trading_day(from_day: date, holidays: dict[str, str] | set[str], limit: int = 30) -> date | None:
    """Next trading day strictly after ``from_day`` (None if beyond limit)."""
    candidate = from_day + timedelta(days=1)
    for _ in range(limit):
        if is_trading_day(candidate, holidays):
            return candidate
        candidate += timedelta(days=1)
    return None


def timings() -> dict[str, Any]:
    """Static NSE equity session timings (IST)."""
    fmt = lambda t: t.strftime("%H:%M")
    return {
        "timezone": "Asia/Kolkata (IST, UTC+5:30)",
        "market_open": fmt(MarketHours.MARKET_OPEN),
        "market_close": fmt(MarketHours.MARKET_CLOSE),
        "pre_market_start": fmt(MarketHours.PRE_MARKET_START),
        "post_market_end": fmt(MarketHours.POST_MARKET_END),
    }


def get_status(now_utc: datetime, holidays: dict[str, str] | set[str]) -> dict[str, Any]:
    """Live open/closed status for ``now_utc`` (naive or aware)."""
    if now_utc.tzinfo is not None:
        now_utc = now_utc.replace(tzinfo=None)
    ist_now = now_utc + IST_OFFSET
    today = ist_now.date()
    key = today.isoformat()
    name = holidays.get(key) if isinstance(holidays, dict) else (key if key in holidays else None)

    if today.weekday() >= 5:
        return _status_payload(ist_now, False, "weekend", None)
    if name:
        return _status_payload(ist_now, False, "holiday", str(name))
    session = get_current_session(ist_now)
    return _status_payload(ist_now, is_trading_session(session), "session", None, session.value)


def _status_payload(ist_now: datetime, is_open: bool, reason: str,
                    holiday: str | None, session: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "is_open": is_open,
        "reason": reason,  # weekend | holiday | session
        "server_time_ist": ist_now.strftime("%Y-%m-%d %H:%M:%S"),
        **timings(),
    }
    if holiday:
        payload["holiday"] = holiday
    if session:
        payload["session"] = session
    return payload
