"""S4 live-quote streaming: WS tick push + REST status/latest/market.

WS auth uses a ``token`` query param (browsers cannot set WS headers);
a bad token is accepted then immediately closed with code 4401 (a
pre-accept close surfaces as HTTP 403/1006 in real browsers, hiding the
code). REST uses the normal Bearer dependency. Ticks come from the poll-based
:mod:`app.services.streaming.hub`; nothing here is fabricated — a symbol
with no successful poll simply has no tick.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.security import decode_token, is_token_revoked
from app.db.models.user import User
from app.db.session import get_session
from app.services import market_calendar as cal
from app.services.data.service import market_data
from app.services.streaming.hub import MAX_SYMBOLS_PER_CONN, hub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streaming", tags=["streaming"])

HEARTBEAT_S = 15.0
WS_CLOSE_UNAUTHORIZED = 4401


def _parse_symbols(raw: str) -> list[str]:
    seen: list[str] = []
    for part in (raw or "").split(","):
        sym = part.strip().upper()
        if sym and sym not in seen:
            seen.append(sym)
    return seen[:MAX_SYMBOLS_PER_CONN]


async def _ws_user(token: str, session: AsyncSession) -> User | None:
    if not token:
        return None
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001 - treat as anonymous
        return None
    if payload is None:
        return None
    if payload.get("jti") and is_token_revoked(payload["jti"]):
        return None
    user = await session.scalar(select(User).where(User.id == payload.get("sub")))
    if user is None or not user.is_active:
        return None
    return user


async def _send_json(ws: WebSocket, obj: dict) -> None:
    await ws.send_text(json.dumps(obj, default=str))


# ------------------------------------------------------------------ REST
@router.get("/status")
async def streaming_status(user: CurrentUser = None) -> dict:
    """Hub health: polled symbols, subscriber count, cache size."""
    return hub.status()


@router.get("/quotes/latest")
async def latest_quotes(
    symbols: str = Query(default="", description="Comma-separated symbols"),
    user: CurrentUser = None,
) -> dict:
    """Fresh quotes fetched now (not cache): null + missing entry on failure."""
    wanted = _parse_symbols(symbols)
    if not wanted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pass ?symbols=SYM1,SYM2")
    quotes: dict[str, dict | None] = {}
    missing: list[str] = []
    for sym in wanted:
        try:
            quote = await market_data.get_quote(sym)
        except Exception as exc:  # noqa: BLE001 - report, don't fail
            quotes[sym] = None
            missing.append(sym)
            logger.warning("streaming latest failed for %s: %s", sym, exc)
            continue
        if not isinstance(quote, dict) or quote.get("price") is None:
            quotes[sym] = None
            missing.append(sym)
        else:
            quotes[sym] = quote
    return {"quotes": quotes, "missing": missing}


@router.get("/market")
async def streaming_market(
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Live market open/closed status (same source as /calendar/status)."""
    now = datetime.utcnow()
    lookup = await cal.holiday_lookup(session, date(2000, 1, 1), date(2100, 1, 1))
    payload = cal.get_status(now, lookup)
    today_ist = (now + cal.IST_OFFSET).date()
    nxt = cal.next_trading_day(today_ist, lookup)
    payload["next_trading_day"] = nxt.isoformat() if nxt else None
    return payload


# ------------------------------------------------------------------ WS
@router.websocket("/quotes")
async def quotes_ws(
    websocket: WebSocket,
    symbols: str = Query(default=""),
    interval_ms: int = Query(default=2000, ge=500, le=60000),
    token: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Push ticks for ``symbols``: snapshot first, then ticks + heartbeats."""
    await websocket.accept()
    if await _ws_user(token, session) is None:
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return
    wanted = _parse_symbols(symbols)
    min_interval = interval_ms / 1000.0
    queue = await hub.subscribe(wanted)
    try:
        snapshot = hub.get_latest(wanted)
        await _send_json(websocket, {
            "type": "snapshot",
            "ticks": [t for t in snapshot.values() if t],
            "symbols": wanted,
        })
        pump = asyncio.create_task(_pump(websocket, queue, min_interval))
        listen = asyncio.create_task(_listen(websocket, queue))
        try:
            done, pending = await asyncio.wait({pump, listen}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if not task.cancelled():
                    exc = task.exception()
                    if exc is not None and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                        raise exc
        except WebSocketDisconnect:
            pass
        finally:
            for task in (pump, listen):
                if not task.done():
                    task.cancel()
            await asyncio.gather(pump, listen, return_exceptions=True)
    finally:
        await hub.unsubscribe(queue)


async def _pump(websocket: WebSocket, queue: asyncio.Queue, min_interval: float) -> None:
    """Forward ticks (throttled to ``min_interval``) + heartbeats."""
    import time

    last_send = 0.0
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
            except asyncio.TimeoutError:
                await _send_json(websocket, {"type": "heartbeat", "ts": datetime.utcnow().isoformat()})
                continue
            now = time.monotonic()
            if now - last_send < min_interval:
                continue
            last_send = now
            await _send_json(websocket, msg)
    except asyncio.CancelledError:
        raise


async def _listen(websocket: WebSocket, queue: asyncio.Queue) -> None:
    """Handle client subscribe/unsubscribe until disconnect."""
    async for raw in websocket.iter_text():
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            await _send_json(websocket, {"type": "error", "detail": "message must be JSON"})
            continue
        action = data.get("action")
        if action in ("subscribe", "unsubscribe"):
            current = set(hub.symbols_of(queue))
            raw_syms = data.get("symbols", [])
            if isinstance(raw_syms, str):  # tolerate a singular string
                raw_syms = [raw_syms]
            delta = set(_parse_symbols(",".join(raw_syms)))
            if action == "subscribe":
                current = (current | delta)
            else:
                current = (current - delta)
            current = set(sorted(current)[:MAX_SYMBOLS_PER_CONN])
            await hub.update(queue, sorted(current))
            await _send_json(websocket, {
                "type": "subscribed" if action == "subscribe" else "unsubscribed",
                "symbols": sorted(current),
            })
        elif action == "refresh":
            current = hub.symbols_of(queue)
            await _send_json(websocket, {
                "type": "snapshot",
                "ticks": [t for t in hub.get_latest(current).values() if t],
                "symbols": current,
            })
        else:
            await _send_json(websocket, {"type": "error", "detail": f"unknown action: {action}"})


@router.websocket("/market")
async def market_ws(
    websocket: WebSocket,
    token: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Push market open/closed status now and every 60s."""
    await websocket.accept()
    if await _ws_user(token, session) is None:
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return
    try:
        while True:
            now = datetime.utcnow()
            lookup = await cal.holiday_lookup(session, date(2000, 1, 1), date(2100, 1, 1))
            payload = cal.get_status(now, lookup)
            await _send_json(websocket, {"type": "market", **payload})
            try:
                async with asyncio.timeout(60):
                    async for raw in websocket.iter_text():
                        try:
                            data = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        if data.get("action") == "refresh":
                            break
            except TimeoutError:
                continue
    except (WebSocketDisconnect, RuntimeError):
        pass
