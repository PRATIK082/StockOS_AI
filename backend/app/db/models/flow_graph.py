"""FlowGraph ORM model (Phase 7).

User-scoped persisted flow strategy: name, definition JSON, optional cron
schedule, enabled flag, and a paper_only guard (default True).
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class FlowGraph(CoreModel):
    __tablename__ = "flow_graphs"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    schedule_cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    paper_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user = relationship("User")
