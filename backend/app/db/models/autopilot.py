"""Autopilot run telemetry models.

``AutopilotRun`` is one full mission of the agent supervisor (day-cycle or
monitor-only); ``AutopilotRunNode`` is the per-agent, per-phase evidence trace
so the UI and the self-review agent can inspect exactly what happened.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class AutopilotRun(CoreModel):
    __tablename__ = "autopilot_runs"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    mission: Mapped[str] = mapped_column(String(24), default="day-cycle", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="running", nullable=False
    )  # running|completed|failed|halted
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    nodes = relationship("AutopilotRunNode", back_populates="run", cascade="all, delete-orphan")


class AutopilotRunNode(CoreModel):
    __tablename__ = "autopilot_run_nodes"

    run_id: Mapped[str] = mapped_column(ForeignKey("autopilot_runs.id"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)  # sentinel|signal|optionstrategy|riskgate|execute|selfreview|debrief
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="done", nullable=False)  # done|skipped|error
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run = relationship("AutopilotRun", back_populates="nodes")