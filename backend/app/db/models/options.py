"""Tracked option position model.

Users can track (paper) PUT/CALL options on an underlying symbol. Strikes and
premiums are stored as strings to avoid floating point drift; quantity is also
a string so fractional lot sizes stay exact.
"""

from __future__ import annotations

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class OptionPosition(CoreModel):
    __tablename__ = "option_positions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    option_type: Mapped[str] = mapped_column(String(8), nullable=False)  # CALL | PUT
    strike: Mapped[str] = mapped_column(String(32), nullable=False)
    expiry: Mapped[str] = mapped_column(Date, nullable=False)
    quantity: Mapped[str] = mapped_column(String(32), default="1", nullable=False)
    premium: Mapped[str] = mapped_column(String(32), default="0", nullable=False)

    user = relationship("User")
