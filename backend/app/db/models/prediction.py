"""Persisted prediction history model.

Every generated AI prediction (underlying and/or CE/PE contract) is stored
per-user so the Prediction page can show old results at runtime instead of
losing them when the page reloads. ``payload`` holds the full result JSON as
returned by ``POST /api/analysis/predict/{symbol}``.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class PredictionHistory(CoreModel):
    __tablename__ = "prediction_history"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), default="1W", nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)

    user = relationship("User")
