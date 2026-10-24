"""Portfolio holding model.

Quantities are stored as strings to avoid floating point drift for fractional
share counts; price/valuation is always recomputed from live market data.
"""

from __future__ import annotations

from sqlalchemy import String, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class Holding(CoreModel):
    __tablename__ = "holdings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[str] = mapped_column(String(32), default="0", nullable=False)
    average_cost: Mapped[str] = mapped_column(String(32), default="0", nullable=False)

    user = relationship("User")
