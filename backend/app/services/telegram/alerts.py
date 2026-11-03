"""Telegram alert emitter (Phase 9c).

``emit()`` is a no-op returning False when the bot is unconfigured or not
running, and it never raises — call sites (order fills, guards) must not be
able to break because of notifications.
"""

from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger("telegram-alerts")


async def emit(event: str, detail: str = "") -> bool:
    """Send ``[event] detail`` to all allowlisted chats. Never raises."""
    try:
        from app.services.telegram import bot as _bot

        app_ = _bot.get_app()
        chats = _bot.chat_ids()
        if app_ is None or not chats:
            return False
        text = f"[{event}] {detail}".strip()[:4000]
        sent = 0
        for chat_id in chats:
            try:
                await app_.bot.send_message(chat_id=chat_id, text=text)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"telegram send to {chat_id} failed: {exc}")
        return sent > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"telegram emit failed: {exc}")
        return False
