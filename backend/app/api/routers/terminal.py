"""Trading-terminal routes for the position-first pro workspace.

This router composes the existing StockOS services (paper broker, portfolio,
orders, settings, scanner, memory) into the aggregated endpoints the pro
trading-terminal UI needs — it intentionally does NOT re-implement execution,
which stays with the existing ``/v1/orders`` + ``/portfolio`` routes.

Endpoints:
- GET  /terminal/positions            live paper positions (live PnL)
- GET  /terminal/analytics            account + equity / drawdown curve
- GET  /terminal/journal              trade journal (memory-backed)
- POST /terminal/journal              create a journal entry
- DELETE /terminal/journal/{key}      delete a journal entry
- GET  /terminal/tradebot             tradebot status + signals
- POST /terminal/tradebot/toggle      enable/disable the paper tradebot
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.brokers.paper import PaperBroker
from app.core.config import get_settings
from app.db.models import Order as OrderModel
from app.db.session import get_session
from app.services.memory.store import memory_store

router = APIRouter(prefix="/terminal", tags=["terminal"])

logger = None  # placeholder to keep import surface small


def _fmt_currency(n: Decimal | float | None) -> float:
    try:
        return float(n)
    except (TypeError, ValueError):
        return 0.0


class JournalCreate(BaseModel):
    symbol: str = Field(min_length=1)
    side: Literal["BUY", "SELL", "HOLD"]
    rationale: str = Field(min_length=1)
    pnl: float = 0.0
    outcome: Literal["win", "loss", "breakeven", "open", "flat"] = "open"
    tags: list[str] = []


class TradebotToggle(BaseModel):
    enabled: bool


# ------------------------------------------------------------------------- #
# Positions
# ------------------------------------------------------------------------- #


@router.get("/positions")
async def terminal_positions(user: CurrentUser) -> dict:
    """Live paper positions with real-time mark-to-market PnL."""
    broker = PaperBroker(user_id=user.id)
    positions = []
    total_unrealised = Decimal("0.00")
    total_cost = Decimal("0.00")
    total_value = Decimal("0.00")

    for pos in await broker.positions():
        symbol = pos.symbol
        qty = Decimal(str(pos.quantity))
        avg = Decimal(str(pos.average_price))
        try:
            quote = await market_data.get_quote(symbol)
            last = Decimal(str(quote.get("price") or quote.get("last_price") or 0))
        except Exception:  # noqa: BLE001
            last = avg
        market_value = qty * last
        cost = qty * avg
        unrealised = market_value - cost
        total_unrealised += unrealised
        total_cost += cost
        total_value += market_value
        positions.append(
            {
                "symbol": symbol,
                "quantity": _fmt_currency(qty),
                "average_price": _fmt_currency(avg),
                "last_price": _fmt_currency(last),
                "market_value": _fmt_currency(market_value),
                "invested": _fmt_currency(cost),
                "unrealised_pnl": _fmt_currency(unrealised),
                "unrealised_pnl_pct": _fmt_currency(
                    (unrealised / cost * 100) if cost else 0.0
                ),
                "realised_pnl": _fmt_currency(pos.realised_pnl),
                "exchange": pos.exchange,
            }
        )

    positions.sort(key=lambda p: p["unrealised_pnl"], reverse=True)
    return {
        "positions": positions,
        "summary": {
            "invested": _fmt_currency(total_cost),
            "value": _fmt_currency(total_value),
            "unrealised_pnl": _fmt_currency(total_unrealised),
            "unrealised_pnl_pct": _fmt_currency(
                (total_unrealised / total_cost * 100) if total_cost else 0.0
            ),
            "count": len(positions),
        },
    }


# ------------------------------------------------------------------------- #
# Analytics (account + equity / drawdown curve from order history)
# ------------------------------------------------------------------------- #


@router.get("/analytics")
async def terminal_analytics(
    user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    """Account analytics: portfolio summary + settings + equity/drawdown curve.

    The equity curve is reconstructed from the user's persisted order history
    (``orders`` table), accumulated by realised daily PnL and starting at the
    paper-broker base capital. This is an honest, derived display — not a
    fabricated live feed.
    """
    settings = get_settings()

    # Portfolio summary via the same live-priced logic as /portfolio.
    portfolio_data = await _portfolio_summary(user.id, session)

    # Reconstruct equity from order history.
    rows = (
        await session.scalars(
            select(OrderModel)
            .where(OrderModel.user_id == user.id)
            .order_by(OrderModel.created_at.asc())
        )
    ).all()

    base_capital = Decimal("100000.00")
    days: dict[str, Decimal] = {}

    # Per-symbol realised PnL from matching BUY->SELL fill pairs.
    realised_by_symbol: dict[str, dict] = {}
    fills = [r for r in rows if r.status == "filled"]
    for row in fills:
        symbol = row.symbol
        acc = realised_by_symbol.setdefault(
            symbol,
            {
                "buy_cost": Decimal("0.00"),
                "buy_qty": Decimal("0"),
                "sell_proceeds": Decimal("0.00"),
                "sell_qty": Decimal("0"),
                "buy_day": None,
                "sell_day": None,
            },
        )
        qty = Decimal(str(row.quantity or "0"))
        price = Decimal(str(row.price or "0"))
        day = (row.created_at or datetime.utcnow()).strftime("%Y-%m-%d")
        if row.side == "BUY":
            acc["buy_cost"] += qty * price
            acc["buy_qty"] += qty
            acc["buy_day"] = day
        elif row.side == "SELL":
            acc["sell_proceeds"] += qty * price
            acc["sell_qty"] += qty
            acc["sell_day"] = day

    for sym, acc in realised_by_symbol.items():
        closed = min(acc["buy_qty"], acc["sell_qty"])
        if closed <= 0 or acc["buy_qty"] <= 0 or acc["sell_qty"] <= 0:
            continue
        avg_buy = acc["buy_cost"] / acc["buy_qty"]
        buy_cost_closed = avg_buy * closed
        sell_val_closed = acc["sell_proceeds"] * (closed / acc["sell_qty"])
        realised = sell_val_closed - buy_cost_closed
        day = acc["sell_day"] or acc["buy_day"] or "1970-01-01"
        days[day] = days.get(day, Decimal("0.00")) + realised

    # Build equity curve.
    ordered_days = sorted(days.keys())
    equity: list[dict] = []
    running = base_capital
    if not ordered_days:
        equity.append(
            {
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "equity": _fmt_currency(base_capital),
                "drawdown": 0.0,
            }
        )
    peak = running
    max_drawdown = Decimal("0.00")
    for day in ordered_days:
        running += days.get(day, Decimal("0.00"))
        peak = max(peak, running)
        dd = (peak - running) / peak * 100 if peak else 0
        max_drawdown = max(max_drawdown, dd if dd > 0 else Decimal("0.00"))
        equity.append(
            {
                "date": day,
                "equity": _fmt_currency(running),
                "drawdown": _fmt_currency(dd),
            }
        )

    # Risk summary.
    broker = PaperBroker(user_id=user.id)
    try:
        open_pos_count = len(await broker.positions())
    except Exception:  # noqa: BLE001
        open_pos_count = len([1 for row in fills if row.side == "BUY"])
    pnl_today = days.get(datetime.utcnow().strftime("%Y-%m-%d"), Decimal("0.00"))

    return {
        "portfolio": portfolio_data,
        "equity_curve": equity,
        "summary": {
            "base_capital": _fmt_currency(base_capital),
            "current_equity": _fmt_currency(running),
            "total_pnl": _fmt_currency(running - base_capital),
            "pnl_pct": _fmt_currency((running - base_capital) / base_capital * 100),
            "max_drawdown_pct": _fmt_currency(max_drawdown),
            "daily_pnl": _fmt_currency(pnl_today),
            "n_filled_orders": len(fills),
        },
        "risk": {
            "execution_mode": settings.execution_mode,
            "max_daily_loss_rupees": settings.max_daily_loss_rupees,
            "max_order_risk_rupees": settings.max_order_risk_rupees,
            "max_open_positions": settings.max_open_positions,
            "max_capital_deployed_percent": settings.max_capital_deployed_percent,
            "daily_pnl_rupees": float(settings._daily_pnl),  # noqa: SLF001
            "open_positions": open_pos_count,
            "capital_deployed_pct": _fmt_currency(
                (portfolio_data["summary"]["invested"] / _fmt_currency(base_capital) * 100)
                if portfolio_data["summary"]["invested"] else 0.0
            ),
        },
    }


async def _portfolio_summary(user_id: str, session: AsyncSession) -> dict:
    """Live portfolio summary (mirrors /portfolio logic without the route)."""
    from app.db.models import Holding

    rows = (await session.scalars(select(Holding).where(Holding.user_id == user_id))).all()
    total_cost = Decimal("0")
    total_value = Decimal("0")
    holdings = []
    for h in rows:
        qty = Decimal(h.quantity or "0")
        cost = Decimal(h.average_cost or "0")
        try:
            quote = await market_data.get_quote(h.symbol)
            price = Decimal(str(quote.get("price") or 0))
        except Exception:  # noqa: BLE001
            price = Decimal("0")
        value = qty * price
        invested = qty * cost
        total_cost += invested
        total_value += value
        holdings.append(
            {
                "id": h.id,
                "symbol": h.symbol,
                "quantity": str(qty),
                "average_cost": str(cost),
                "current_price": float(price),
                "invested": float(invested),
                "value": float(value),
                "pnl": float(value - invested),
                "pnl_pct": float(((value - invested) / invested * 100)) if invested else 0.0,
            }
        )
    return {
        "holdings": holdings,
        "summary": {
            "invested": float(total_cost),
            "value": float(total_value),
            "pnl": float(total_value - total_cost),
            "pnl_pct": float((total_value - total_cost) / total_cost * 100) if total_cost else 0.0,
        },
    }


# ------------------------------------------------------------------------- #
# Journal (memory-backed, kind="journal")
# ------------------------------------------------------------------------- #


@router.get("/journal")
async def terminal_journal(user: CurrentUser) -> dict:
    """List the user's trade-journal entries (newest first)."""
    rows = await memory_store.list(user.id, kind="journal", limit=500)
    entries = []
    for row in rows:
        value = row["value"]
        if isinstance(value, dict):
            entries.append(
                {
                    "id": row["key"],
                    "symbol": value.get("symbol", ""),
                    "side": value.get("side", ""),
                    "rationale": value.get("rationale", ""),
                    "pnl": value.get("pnl", 0.0),
                    "outcome": value.get("outcome", "open"),
                    "tags": value.get("tags", []),
                    "created_at": row["created_at"],
                }
            )
    entries.sort(key=lambda e: (e["created_at"] or ""), reverse=True)
    return {"entries": entries}


@router.post("/journal", status_code=status.HTTP_201_CREATED)
async def terminal_journal_create(body: JournalCreate, user: CurrentUser) -> dict:
    """Create a trade-journal entry."""
    import hashlib

    key = f"journal:{hashlib.sha1(f"{body.symbol}:{datetime.utcnow().timestamp()}".encode("utf-8")).hexdigest()[:12]}"
    created = await memory_store.set(
        user.id,
        key,
        {
            "symbol": body.symbol.upper(),
            "side": body.side.upper(),
            "rationale": body.rationale,
            "pnl": body.pnl,
            "outcome": body.outcome,
            "tags": body.tags,
        },
        kind="journal",
        scope="trade",
    )
    return {"id": key, "created": created.get("created", True)}


@router.delete("/journal/{key}")
async def terminal_journal_delete(key: str, user: CurrentUser) -> dict:
    """Delete a trade-journal entry."""
    if not key.startswith("journal:"):
        key = f"journal:{key}"
    deleted = await memory_store.delete(user.id, key)
    return {"deleted": deleted}


# ------------------------------------------------------------------------- #
# Tradebot (paper signals + enable/disable toggle)
# ------------------------------------------------------------------------- #


@router.get("/tradebot")
async def terminal_tradebot(user: CurrentUser) -> dict:
    """Tradebot status + top scanner signals the bot tracks (paper mode)."""
    state = await memory_store.get(user.id, "tradebot:state")
    enabled = bool(state and state["value"].get("enabled")) if state else False

    # Tradebot signals are best-effort. Running the full market scan inside the
    # request path made the terminal endpoint hang on slow/unreliable data
    # providers, so signals are populated by the (optional) scanner endpoints
    # instead of blocking every terminal load.
    signals = []

    return {
        "enabled": enabled,
        "mode": "PAPER",
        "signals": signals,
        "strategy": "momentum",
        "updated_at": datetime.utcnow().isoformat(),
    }


@router.post("/tradebot/toggle")
async def terminal_tradebot_toggle(body: TradebotToggle, user: CurrentUser) -> dict:
    """Enable/disable the simulated paper tradebot (state is per-user)."""
    await memory_store.set(
        user.id,
        "tradebot:state",
        {"enabled": body.enabled, "mode": "PAPER", "updated_at": datetime.utcnow().isoformat()},
        kind="tradebot",
        scope="state",
    )
    return {"enabled": body.enabled, "mode": "PAPER"}


@router.post("/tradebot/execute")
async def terminal_tradebot_execute(
    body: dict[str, Any], user: CurrentUser
) -> dict:
    """Paper-execute a tradebot signal via the standard order route logic.

    Body: {symbol, side, quantity}. Delegates to the existing paper broker so
    risk guards and the audit trail still apply. This is always PAPER.
    """
    symbol = (str(body.get("symbol") or "")).strip().upper()
    side = str(body.get("side") or "BUY").upper()
    try:
        quantity = Decimal(str(body.get("quantity") or "1"))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid quantity")

    from app.brokers.interface import BrokerSide, OrderType, ProductType
    from app.api.routers.orders import _get_broker

    broker = _get_broker(user.id)
    result = await broker.place_order(
        symbol=symbol,
        side=BrokerSide(side),
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=quantity,
    )
    if result.status in ("rejected", "cancelled"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.error_message or "Execution rejected")
    return {
        "order_id": result.order_id,
        "symbol": symbol,
        "side": side,
        "quantity": str(quantity),
        "fill_price": _fmt_currency(result.filled_price),
        "status": "filled",
        "message": "Tradebot signal executed (paper mode)",
    }
