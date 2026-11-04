"""Telegram config helpers (Phase 9c): load + decrypt, never log the token."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.telegram import TelegramConfig
from app.db.session import SessionFactory

logger = get_logger("telegram-config")


async def load_config() -> TelegramConfig | None:
    """Return the singleton config row, or None when never configured."""
    async with SessionFactory() as session:
        return (
            await session.execute(select(TelegramConfig).limit(1))
        ).scalar_one_or_none()


async def save_config(*, token: str | None, chat_ids: list[int] | None,
                      enabled: bool | None, owner_user_id: str) -> TelegramConfig:
    """Upsert the singleton row. ``token=None`` leaves the stored token alone;
    ``token=""`` clears it. Returns the row (detached)."""
    async with SessionFactory() as session:
        cfg = (await session.execute(select(TelegramConfig).limit(1))).scalar_one_or_none()
        if cfg is None:
            cfg = TelegramConfig(owner_user_id=owner_user_id)
            session.add(cfg)
        if token is not None:
            cfg.token_encrypted = encrypt_secret(token) if token else None
        if chat_ids is not None:
            cfg.chat_ids = json.dumps([int(c) for c in chat_ids])
        if enabled is not None:
            cfg.enabled = bool(enabled)
        cfg.owner_user_id = owner_user_id
        await session.commit()
        await session.refresh(cfg)
        session.expunge(cfg)
        return cfg


def get_token(cfg: TelegramConfig) -> str | None:
    """Decrypt the stored token; None when absent or undecryptable."""
    if not cfg.token_encrypted:
        return None
    try:
        return decrypt_secret(cfg.token_encrypted)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"telegram token undecryptable: {exc}")
        return None


def get_chat_ids(cfg: TelegramConfig) -> list[int]:
    try:
        return [int(c) for c in json.loads(cfg.chat_ids or "[]")]
    except (ValueError, TypeError):
        return []
