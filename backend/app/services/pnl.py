"""PnL tracker service (Phase 9b).

Realized PnL is computed with FIFO lot matching over the user's *filled*
orders — no new capture needed. Unrealized PnL reuses holdings + live quotes
(the same basis as the portfolio endpoint). The equity curve is a step
function of cumulative realized PnL at fill timestamps; historical unrealized
is not captured in v1, so the final point is flagged ``live`` and includes
current unrealized explicitly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

RANGE_WINDOWS = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
    "all": None,
}


def fifo_realized(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """FIFO realized PnL over fills [{symbol, side, quantity, price}].

    Returns {total, per_symbol: {sym: gain}, wins, losses, flats, sells}.
    Buys push lots; sells consume oldest lots first. Short sells (no lots)
    are ignored for realized purposes — paper mode is long-only in v1.
    """
    lots: dict[str, list[list[Decimal]]] = {}
    per_symbol: dict[str, Decimal] = {}
    wins = losses = flats = sells = 0
    for fill in fills:
        sym = str(fill["symbol"])
        qty = Decimal(str(fill.get("quantity") or "0"))
        price = Decimal(str(fill.get("price") or "0"))
        if qty <= 0 or price < 0:
            continue
        if str(fill.get("side", "")).upper() == "BUY":
            lots.setdefault(sym, []).append([qty, price])
            per_symbol.setdefault(sym, Decimal("0"))
            continue
        # SELL: consume oldest lots.
        sells += 1
        remaining = qty
        gain = Decimal("0")
        queue = lots.get(sym, [])
        while remaining > 0 and queue:
            lot_qty, lot_price = queue[0]
            matched = min(lot_qty, remaining)
            gain += (price - lot_price) * matched
            lot_qty -= matched
            remaining -= matched
            if lot_qty <= 0:
                queue.pop(0)
            else:
                queue[0][0] = lot_qty
        # Unmatched remainder (no cost basis) contributes nothing — not fabricated.
        per_symbol[sym] = per_symbol.get(sym, Decimal("0")) + gain
        if gain > 0:
            wins += 1
        elif gain < 0:
            losses += 1
        else:
            flats += 1
    return {
        "total": float(sum(per_symbol.values(), Decimal("0"))),
        "per_symbol": {sym: float(g) for sym, g in sorted(per_symbol.items())},
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "sells": sells,
    }


async def filled_orders(user_id: str, session: AsyncSession,
                        since: datetime | None = None) -> list[Any]:
    """User's filled orders, oldest first, optionally filtered by created_at."""
    from app.db.models.order import Order

    stmt = select(Order).where(Order.user_id == user_id, Order.status == "filled")
    if since is not None:
        stmt = stmt.where(Order.created_at >= since)
    stmt = stmt.order_by(Order.created_at.asc())
    return list((await session.execute(stmt)).scalars().all())


async def unrealized(user_id: str, session: AsyncSession) -> dict[str, Any]:
    """Current unrealized PnL from holdings + live quotes (0 on quote failure)."""
    from decimal import Decimal as D

    from app.db.models import Holding
    from app.services.data.service import market_data

    rows = (await session.scalars(select(Holding).where(Holding.user_id == user_id))).all()
    total = D("0")
    positions = []
    for h in rows:
        qty = D(h.quantity or "0")
        cost = D(h.average_cost or "0")
        try:
            quote = await market_data.get_quote(h.symbol)
            price = D(str(quote.get("price") or 0))
            live = True
        except Exception:  # noqa: BLE001
            price = D("0")
            live = False
        pnl = (price - cost) * qty if live else D("0")
        total += pnl
        positions.append({"symbol": h.symbol, "quantity": str(qty), "pnl": float(pnl), "live": live})
    return {"total": float(total), "positions": positions}
