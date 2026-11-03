"""Telegram bot worker, read-only v1 (Phase 9c).

Long-polling ``Application`` started/stopped with the app lifespan. Commands
are read-only by design: /start, /status, /positions, /pnl. Approvals stay in
the web UI deliberately. Only allowlisted chats get answers.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from app.core.logging import get_logger
from app.services.telegram import config as tg_config

logger = get_logger("telegram")

_APP: Any | None = None
_CHAT_IDS: list[int] = []


def get_app() -> Any | None:
    return _APP


def chat_ids() -> list[int]:
    return list(_CHAT_IDS)


async def _guard(update: Any) -> int | None:
    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None) if chat else None
    if chat_id is None or int(chat_id) not in _CHAT_IDS:
        message = getattr(update, "message", None)
        if message is not None:
            await message.reply_text("Not authorized for this bot.")
        return None
    return int(chat_id)


async def start_cmd(update: Any, context: Any) -> None:
    if await _guard(update) is None:
        return
    await update.message.reply_text(
        "StockOS notifications bot (read-only).\n"
        "/status - market + mode\n"
        "/positions - holdings + unrealized PnL\n"
        "/pnl - realized + total PnL"
    )


async def status_cmd(update: Any, context: Any) -> None:
    if await _guard(update) is None:
        return
    await update.message.reply_text(await build_status_text())


async def positions_cmd(update: Any, context: Any) -> None:
    if await _guard(update) is None:
        return
    await update.message.reply_text(await build_positions_text(_owner_id(context)))


async def pnl_cmd(update: Any, context: Any) -> None:
    if await _guard(update) is None:
        return
    await update.message.reply_text(await build_pnl_text(_owner_id(context)))


def _owner_id(context: Any) -> str | None:
    try:
        return context.application.bot_data.get("owner_user_id")
    except AttributeError:
        return None


async def build_status_text() -> str:
    from app.core.config import get_settings
    from app.services import market_calendar as cal

    async with _session() as session:
        lookup = await cal.holiday_lookup(session, date(2000, 1, 1), date(2100, 1, 1))
    st = cal.get_status(datetime.utcnow(), lookup)
    d = get_settings()
    state = "OPEN" if st["is_open"] else "CLOSED"
    extra = st.get("session") or st.get("reason") or ""
    return f"Market: {state} ({extra})\nMode: {d.execution_mode} / {d.broker}"


async def build_positions_text(owner_user_id: str | None) -> str:
    if not owner_user_id:
        return "Bot owner not linked."
    from app.services import pnl as pnl_svc

    async with _session() as session:
        un = await pnl_svc.unrealized(owner_user_id, session)
    lines = [f"Holdings: {len(un['positions'])}  Unrealized: Rs {un['total']:.2f}"]
    for p in un["positions"][:10]:
        live = "" if p["live"] else " (stale)"
        lines.append(f"{p['symbol']} x{p['quantity']}: Rs {p['pnl']:.2f}{live}")
    return "\n".join(lines)


async def build_pnl_text(owner_user_id: str | None) -> str:
    if not owner_user_id:
        return "Bot owner not linked."
    from app.services import pnl as pnl_svc

    async with _session() as session:
        fills = await pnl_svc.filled_orders(owner_user_id, session)
        realized = pnl_svc.fifo_realized(
            [{"symbol": o.symbol, "side": o.side, "quantity": o.quantity, "price": o.price}
             for o in fills]
        )
        un = await pnl_svc.unrealized(owner_user_id, session)
    total = realized["total"] + un["total"]
    return (
        f"Realized: Rs {realized['total']:.2f} "
        f"({realized['wins']}W/{realized['losses']}L)\n"
        f"Unrealized: Rs {un['total']:.2f}\n"
        f"Total: Rs {total:.2f}"
    )


def _session():
    from app.db.session import SessionFactory

    return SessionFactory()


async def start_bot() -> bool:
    """Start polling when configured + enabled + token decrypts. Else False."""
    global _APP, _CHAT_IDS
    if _APP is not None:
        return True
    try:
        cfg = await tg_config.load_config()
        if cfg is None or not cfg.enabled:
            return False
        token = tg_config.get_token(cfg)
        if not token:
            logger.warning("telegram configured but token missing/undecryptable; bot not started")
            return False
        from telegram.ext import Application, CommandHandler

        _CHAT_IDS = tg_config.get_chat_ids(cfg)
        app_ = Application.builder().token(token).build()
        app_.add_handler(CommandHandler("start", start_cmd))
        app_.add_handler(CommandHandler("status", status_cmd))
        app_.add_handler(CommandHandler("positions", positions_cmd))
        app_.add_handler(CommandHandler("pnl", pnl_cmd))
        app_.bot_data["owner_user_id"] = cfg.owner_user_id
        await app_.initialize()
        await app_.start()
        await app_.updater.start_polling()
        _APP = app_
        logger.info(f"telegram bot started ({len(_CHAT_IDS)} chats allowlisted)")
        return True
    except Exception as exc:  # noqa: BLE001 - bot must never break startup
        logger.warning(f"telegram bot failed to start: {exc}")
        _APP = None
        return False


async def stop_bot() -> None:
    """Stop polling; always safe to call."""
    global _APP, _CHAT_IDS
    app_, _APP = _APP, None
    _CHAT_IDS = []
    if app_ is None:
        return
    try:
        await app_.updater.stop()
        await app_.stop()
        await app_.shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"telegram bot stop issue: {exc}")


async def send_test() -> bool:
    """Send a test message to all allowlisted chats. False when not running."""
    from app.services.telegram import alerts

    return await alerts.emit("test", "StockOS Telegram notifications are working.")
