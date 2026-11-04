"""Market holiday admin overlay (Phase 9d).

Seed holidays live in ``app/data/nse_holidays.json``. Rows here override the
seed: an admin row with the same date replaces the seed name, and a row with
``removed=True`` hides a seed date without editing the JSON file.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import CoreModel


class MarketHoliday(CoreModel):
    __tablename__ = "market_holidays"

    date: Mapped[date] = mapped_column(Date, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
