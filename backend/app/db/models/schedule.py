"""ScheduledResearch + ScheduledRun models.

A schedule ties a cron expression (in an IANA timezone) to a playbook —
currently a deterministic data workflow (swarm preset, technical summary,
backtest, factor IC) run by the scheduler runner. Runs persist their output
JSON in ``scheduled_runs``.
"""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class ScheduledResearch(CoreModel):
    __tablename__ = "scheduled_research"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    playbook: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    runs = relationship("ScheduledRun", back_populates="schedule", cascade="all, delete-orphan")


class ScheduledRun(CoreModel):
    __tablename__ = "scheduled_runs"

    schedule_id: Mapped[str] = mapped_column(
        ForeignKey("scheduled_research.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)  # JSON
    started_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)

    schedule = relationship("ScheduledResearch", back_populates="runs")
