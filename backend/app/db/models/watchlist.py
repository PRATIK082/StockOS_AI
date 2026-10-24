"""Watchlist model.

A watchlist groups symbols a user tracks. Symbols are namespaced by exchange,
e.g. `NSE:RELIANCE` or `NYSE:AAPL`.
"""

from __future__ import annotations

from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class Watchlist(CoreModel):
    __tablename__ = "watchlists"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), default="Default", nullable=False)
    symbols: Mapped[str] = mapped_column(String(2000), default="", nullable=False)

    user = relationship("User")
