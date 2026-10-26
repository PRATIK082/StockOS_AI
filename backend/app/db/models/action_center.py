"""Action Center model for human-in-the-loop order approvals."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, ForeignKey, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class ActionCenterItem(CoreModel):
    __tablename__ = "action_center"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY | SELL
    quantity: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending | approved | rejected | executed
    order_type: Mapped[str] = mapped_column(String(16), nullable=True)
    payload: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")
