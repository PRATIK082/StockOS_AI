"""Trading Desk persistence models.

- ``ProviderCredential``: a user's saved LLM provider setup for the trading
  engine. The API key is stored Fernet-encrypted (see
  ``app.core.security.encrypt_secret``); raw keys are never persisted.
- ``TradingRun``: one completed (or failed) engine run and its decision.
- ``TradingRunNode``: ordered step trace of the run for the live status panel
  and history.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class ProviderCredential(CoreModel):
    __tablename__ = "trading_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_trading_cred_user_provider"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    deep_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quick_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user = relationship("User")


class TradingRun(CoreModel):
    __tablename__ = "trading_runs"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_date: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    deep_model: Mapped[str] = mapped_column(String(128), nullable=False)
    quick_model: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)  # running|completed|failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    rating: Mapped[str | None] = mapped_column(String(24), nullable=True)
    signal_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    reports_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_trace_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    nodes = relationship("TradingRunNode", back_populates="run", cascade="all, delete-orphan")


class TradingRunNode(CoreModel):
    __tablename__ = "trading_run_nodes"

    run_id: Mapped[str] = mapped_column(ForeignKey("trading_runs.id"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    repeat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run = relationship("TradingRun", back_populates="nodes")