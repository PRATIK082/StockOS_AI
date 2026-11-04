"""StrategyScript ORM model (Phase 8).

User-scoped persisted Python strategy: name, source code, optional cron
schedule, enabled flag.

Env storage decision: per-script encrypted env vars live in the
``env_encrypted`` TEXT column on this row (Fernet-encrypted JSON dict via
``app.core.security.encrypt_secret`` / ``decrypt_secret`` — the exact same
pattern as stored broker credentials). A sibling table was considered but a
single encrypted blob is sufficient for v1 (flat string map, write-only
values) and keeps the model surface to one table. Values are NEVER returned
by any API; only key names are exposed.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import CoreModel


class StrategyScript(CoreModel):
    __tablename__ = "strategy_scripts"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    schedule_cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Fernet-encrypted JSON object {"KEY": "value"} (see module docstring).
    env_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User")
