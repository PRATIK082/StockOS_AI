"""Order model for tracking submitted and filled orders."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class Order(CoreModel):
    __tablename__ = "orders"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY | SELL
    quantity: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending | filled | cancelled
    order_type: Mapped[str] = mapped_column(String(16), nullable=True)  # MARKET | LIMIT
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    extra_data: Mapped[str] = mapped_column(String(500), nullable=True)  # JSON string for extra data

    user = relationship("User")