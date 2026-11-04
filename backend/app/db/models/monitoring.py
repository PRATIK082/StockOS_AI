"""Request metrics model for the Phase 9a monitoring middleware."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import CoreModel


class RequestMetric(CoreModel):
    __tablename__ = "request_metrics"

    route: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False, default="GET")
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
