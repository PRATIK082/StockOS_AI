"""Telegram notification routes (Phase 9c).

The bot token is write-only: it can be set or cleared, but no endpoint ever
returns it. Commands are read-only v1 (/start, /status, /positions, /pnl).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, require_role
from app.db.models.user import User
from app.services.telegram import bot as tg_bot
from app.services.telegram import config as tg_config

router = APIRouter(prefix="/telegram", tags=["telegram"])

AdminUser = Annotated[User, Depends(require_role("admin"))]


class TelegramConfigIn(BaseModel):
    token: str | None = Field(None, description="Bot token; null leaves it, empty clears it")
    chat_ids: list[int] | None = Field(None, description="Allowlisted chat IDs")
    enabled: bool | None = None


def _status_shape(cfg: Any, running: bool) -> dict[str, Any]:
    return {
        "configured": bool(cfg is not None and cfg.token_encrypted),
        "enabled": bool(cfg is not None and cfg.enabled),
        "running": running,
        "chat_ids": tg_config.get_chat_ids(cfg) if cfg is not None else [],
        "owner_linked": bool(cfg is not None and cfg.owner_user_id),
    }


@router.get("/status")
async def status(user: CurrentUser = None) -> Any:
    """Bot status for the settings card. Never includes the token."""
    cfg = await tg_config.load_config()
    return _status_shape(cfg, tg_bot.get_app() is not None)


@router.put("/config")
async def save_config(body: TelegramConfigIn, user: AdminUser = None) -> Any:
    """Save bot config (admin). Token is write-only; restarts the bot to apply."""
    cfg = await tg_config.save_config(
        token=body.token,
        chat_ids=body.chat_ids,
        enabled=body.enabled,
        owner_user_id=user.id,
    )
    await tg_bot.stop_bot()
    running = await tg_bot.start_bot()
    return _status_shape(cfg, running)


@router.post("/test")
async def test_message(user: AdminUser = None) -> Any:
    """Send a test message to allowlisted chats (admin)."""
    if tg_bot.get_app() is None:
        raise HTTPException(409, "Telegram bot is not running")
    ok = await tg_bot.send_test()
    return {"ok": ok}


@router.post("/restart")
async def restart(user: AdminUser = None) -> Any:
    """Restart the polling worker (admin)."""
    await tg_bot.stop_bot()
    running = await tg_bot.start_bot()
    cfg = await tg_config.load_config()
    return _status_shape(cfg, running)
