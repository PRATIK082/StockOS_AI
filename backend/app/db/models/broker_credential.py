"""Per-user broker credentials + last auth result (Phase 9e).

Secrets are Fernet-encrypted and write-only: no endpoint ever returns them.
``last_auth_*`` records the outcome of the last ``auth/verify`` call so the
diagnostics card can show it without re-checking.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class BrokerCredential(CoreModel):
    __tablename__ = "broker_credentials"
    __table_args__ = (UniqueConstraint("user_id", "broker", name="uq_broker_cred_user_broker"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    broker: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_seed_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_auth_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_auth_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_auth_error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    user = relationship("User")
