"""Master contract store (broker symbol metadata)."""

from __future__ import annotations

from sqlalchemy import String, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import CoreModel


class MasterContract(CoreModel):
    __tablename__ = "master_contracts"

    symbol: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(16), nullable=False, default="EQUITY")
    underlying: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expiry: Mapped[str | None] = mapped_column(String(16), nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    broker: Mapped[str | None] = mapped_column(String(32), nullable=True)
