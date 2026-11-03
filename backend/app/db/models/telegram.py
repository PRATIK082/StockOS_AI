"""Telegram bot configuration (Phase 9c, read-only v1).

Singleton row: the bot token is Fernet-encrypted (write-only via API, never
returned), ``chat_ids`` is a JSON list allowlist, and ``owner_user_id`` is the
admin whose data the read-only commands report on (single-owner v1).
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class TelegramConfig(CoreModel):
    __tablename__ = "telegram_config"

    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )

    owner = relationship("User")
