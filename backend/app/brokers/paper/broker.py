"""PaperBroker - simulated execution adapter for StockOS.

IMPORTANT:
- This broker **never** sends orders to any external exchange.
- All fills happen at the **next bar's open** price (same convention as
  the backtesting engine ``engine_v2.py``).
- Brokerage/slippage are configurable percentages applied to the notional.
- Order status, positions, P&L, and audit history are persisted in the
  local SQLite database.
- This broker is the *only* routing target when ``execution_mode`` is
  ``PAPER`` or ``REQUIRE_APPROVAL``.
- When ``execution_mode`` is ``LIVE_ENABLED`` the API endpoint
  ``POST /api/v1/orders/submit`` must **reject** the order unless the
  user has explicitly configured LIVE_ENABLED and valid broker credentials.

Convention used throughout:
- Symbols are ``EXCHANGE:TICKER`` form, e.g. ``NSE:RELIANCE``.
- Quantities are ``Decimal`` to avoid float drift.
- Prices are ``Decimal``.
- All rupee amounts are ``int``-friendly when multiplied by 100 (to stay
  in paisa), but we expose ``Decimal`` for readability.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.brokers.interface import (
    BrokerBase,
    BrokerConnectRequest,
    BrokerConnectResponse,
    BrokerFunds,
    BrokerOrderResult,
    BrokerOrderStatus,
    BrokerQuote,
    BrokerPosition,
    BrokerSide,
    BrokerOrders,
    ProductType,
    OrderType,
)
from app.core.config import get_settings
from app.db.base import Base
from sqlalchemy import Table, Column, Integer, String, DateTime, MetaData, Text, func, insert, select

# ------------------------------------------------------------------------- #
# PaperBroker configuration (in-memory, process-local)
# ------------------------------------------------------------------------- #

PAPER_BROKER_DB_PATH = Path(__file__).parent / "paper_broker_audit.db"
"""SQLite file used by PaperBroker for audit history and state."""

# ------------------------------------------------------------------------- #
# Internal helper - DB schema creation (run once at import)
# ------------------------------------------------------------------------- #

_metadata = MetaData()

paper_audit = Table(
    "paper_order_audit",
    _metadata,
    Column("id", Integer, primary_key=True, index=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("local_order_id", String, nullable=False),
    Column("broker_order_id", String, nullable=True),
    Column("symbol", String, nullable=False),
    Column("exchange", String, nullable=False),
    Column("side", String, nullable=False),
    Column("product", String, nullable=False),
    Column("order_type", String, nullable=False),
    Column("quantity", String, nullable=False),  # stored as string Decimal
    Column("price", String, nullable=True),  # limit price
    Column("stop_loss", String, nullable=True),
    Column("target", String, nullable=True),
    Column("filled_quantity", String, nullable=True),
    Column("filled_price", String, nullable=True),
    Column("avg_price", String, nullable=True),
    Column("status", String, nullable=False),
    Column("pnl", String, nullable=True),  # realised P&L
    Column("error_message", String, nullable=True),
    Column("client_payload", String, nullable=True),  # JSON snapshot of request
)


# Create the DB + tables on first import
def _init_db() -> None:
    """Create the SQLite DB and audit table if they don't exist."""
    with sqlite3.connect(str(PAPER_BROKER_DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_order_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                local_order_id TEXT NOT NULL,
                broker_order_id TEXT,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                side TEXT NOT NULL,
                product TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity TEXT NOT NULL,
                price TEXT,
                stop_loss TEXT,
                target TEXT,
                filled_quantity TEXT,
                filled_price TEXT,
                avg_price TEXT,
                status TEXT NOT NULL,
                pnl TEXT,
                error_message TEXT,
                client_payload TEXT
            )
            """
        )
        conn.commit()


_init_db()  # idempotent - ensures audit table exists


# ------------------------------------------------------------------------- #
# PaperBroker implementation
# ------------------------------------------------------------------------- #


class PaperBroker(BrokerBase):
    """Simulated broker that fills orders at the next market data bar open.

    Features:
    - Fills at next available quote ``last_price`` (or simulated close price).
    - Applies configurable brokerage + slippage percentages.
    - Tracks positions, average cost, realised + unrealised P&L.
    - Immutable audit history in SQLite.
    - Daily loss limiting (checked against ``get_settings().max_daily_loss_rupees``).
    - Duplicate-order prevention (same symbol + side + day -> reject).
    - Square-off and kill-switch close all positions at market.
    - Thread-safe via a module-level asyncio Lock.
    """
    name: str = "paper"

    # ------------------------------------------------------------------
    # Private state (protected by ``_lock``)
    # ------------------------------------------------------------------
    _lock = asyncio.Lock()
    # Maps local_order_id -> BrokerOrderResult (in-memory index)
    _order_index: Dict[str, BrokerOrderResult] = {}
    # Maps symbol -> position info dict
    _position_index: Dict[str, dict] = {}
    # Tracks daily gross P&L for loss-limit check (resets at UTC midnight)
    _daily_gross_pnl: Decimal = Decimal("0.00")
    # Tracks the last "trade date" for daily reset
    _last_trade_date: Optional[str] = None

    def __init__(self, **kwargs: Any) -> None:
        """Accept optional session/user_id for API compatibility."""
        self._session = kwargs.get("session")
        self._user_id = kwargs.get("user_id")
        self._analyzer_mode = bool(kwargs.get("analyzer_mode", False))
        self._allow_duplicate_orders = False
        try:
            if "analyzer_mode" not in kwargs:
                self._analyzer_mode = bool(get_settings().analyzer_mode)
        except Exception:
            pass

    @property
    def analyzer_mode(self) -> bool:
        try:
            if getattr(self, "_analyzer_mode", False):
                return True
            return bool(get_settings().analyzer_mode)
        except Exception:
            return bool(getattr(self, "_analyzer_mode", False))

    @analyzer_mode.setter
    def analyzer_mode(self, value: bool) -> None:
        self._analyzer_mode = bool(value)
        try:
            get_settings().analyzer_mode = bool(value)
        except Exception:
            pass

    def enable_analyzer(self) -> None:
        self.analyzer_mode = True

    def disable_analyzer(self) -> None:
        self.analyzer_mode = False

    def toggle_analyzer(self, enabled: bool | None = None) -> bool:
        if enabled is None:
            enabled = not self.analyzer_mode
        self.analyzer_mode = bool(enabled)
        return self.analyzer_mode

    # ------------------------------------------------------------------
    # Internal: connect - paper broker is always "connected"
    # ------------------------------------------------------------------
    async def connect(self, credentials: BrokerConnectRequest) -> BrokerConnectResponse:
        """Paper broker is always authenticated; we just validate the payload."""
        return BrokerConnectResponse(
            authenticated=True,
            access_token=None,
            expires_at=None,
            message="Paper broker - always connected; no real credentials required.",
        )

    # ------------------------------------------------------------------
    # PaperBroker: connection_status
    # ------------------------------------------------------------------
    async def connection_status(self) -> Dict[str, Any]:
        return {
            "online": True,
            "broker_name": self.name,
            "last_checked": datetime.utcnow(),
            "error": None,
        }

    # ------------------------------------------------------------------
    # PaperBroker: funds - simulated cash balance from settings
    # ------------------------------------------------------------------
    async def funds(self) -> BrokerFunds:
        settings = get_settings()
        if self.analyzer_mode:
            cash = Decimal(str(settings.analyzer_sandbox_capital))
        else:
            cash = Decimal("100000.00")  # 1 lakh simulated starting capital
        margin_available = cash * Decimal(str(settings.max_capital_deployed_percent)) / Decimal("100.0")
        if self.analyzer_mode:
            margin_available = cash * Decimal(str(settings.analyzer_margin_percent)) / Decimal("100.0")
        equity = cash
        return BrokerFunds(
            cash=cash,
            margin_available=margin_available,
            equity=equity,
        )

    # ------------------------------------------------------------------
    # PaperBroker: quote - pull from the last known market data.
    # ------------------------------------------------------------------
    async def quote(self, symbol: str) -> BrokerQuote:
        from app.services.data.service import market_data
        try:
            q = await market_data.quote(symbol)
            last_price = Decimal(str(q.get("last_price", q.get("last", "0"))))
            bid = Decimal(str(q.get("bid", last_price)))
            ask = Decimal(str(q.get("ask", last_price)))
            volume = int(q.get("volume", 0))
            return BrokerQuote(
                symbol=symbol,
                exchange=symbol.split(":")[0] if ":" in symbol else "NSE",
                last_price=last_price,
                bid=bid,
                ask=ask,
                volume=volume,
                open=last_price,
                high=last_price,
                low=last_price,
                close=last_price,
                timestamp=datetime.utcnow(),
            )
        except Exception:
            base = Decimal("1000.00")
            return BrokerQuote(
                symbol=symbol,
                exchange=symbol.split(":")[0] if ":" in symbol else "NSE",
                last_price=base,
                bid=base - Decimal("1.00"),
                ask=base + Decimal("1.00"),
                volume=1000,
                open=base,
                high=base + Decimal("5.00"),
                low=base - Decimal("5.00"),
                close=base,
                timestamp=datetime.utcnow(),
            )

    # ------------------------------------------------------------------
    # Core: place_order - simulate fill at next bar open
    # ------------------------------------------------------------------
    async def place_order(
        self,
        symbol: str,
        side: BrokerSide,
        product: ProductType,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        stop_loss: Optional[Decimal] = None,
        target: Optional[Decimal] = None,
    ) -> BrokerOrderResult:
        async with self._lock:
            return await self._place_order_unlocked(
                symbol, side, product, order_type, quantity, price, stop_loss, target
            )

    async def _place_order_unlocked(
        self,
        symbol: str,
        side: BrokerSide,
        product: ProductType,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        stop_loss: Optional[Decimal] = None,
        target: Optional[Decimal] = None,
    ) -> BrokerOrderResult:
        """Core order logic without lock acquisition (used by square_off/kill_switch)."""
        # 1. Validation
        validation = await self._validate_order(
            symbol, side, product, order_type, quantity, price, stop_loss, target
        )
        if not validation["allowed"]:
            return BrokerOrderResult(
                order_id=f"paper-{datetime.utcnow().timestamp()}",
                status=BrokerOrderStatus.REJECTED,
                symbol=symbol,
                exchange=symbol.split(":")[0] if ":" in symbol else "NSE",
                product=product,
                side=side if isinstance(side, str) else side.value,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_loss=stop_loss,
                target=target,
                error_message=validation["reason"],
                client_payload=json.dumps(
                    {
                        "symbol": symbol,
                        "side": side if isinstance(side, str) else side.value,
                        "product": product if isinstance(product, str) else product.value,
                        "order_type": order_type if isinstance(order_type, str) else order_type.value,
                        "quantity": str(quantity),
                        "price": str(price) if price else None,
                    }
                ),
            )

        # 2. Determine fill price
        quote = await self.quote(symbol)
        fill_price = await self._compute_fill_price(
            order_type, price, quote, stop_loss, target, side
        )

        # 3. Compute brokerage + slippage
        brokerage_pct = Decimal("0.001")  # 0.1%
        slippage_pct = Decimal("0.0005")  # 0.05%
        notional = abs(quantity) * fill_price
        brokerage = (notional * brokerage_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        slippage_adj = (notional * slippage_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # 4. Compute fills
        gross_returns = Decimal("0.00")
        if side == BrokerSide.BUY:
            total_cost = fill_price * abs(quantity) + slippage_adj + brokerage
            self._update_position(symbol, side, quantity, fill_price)
        else:  # SELL
            total_proceeds = fill_price * abs(quantity) - slippage_adj - brokerage
            pos_info_before = self._position_index.get(symbol)
            avg_before = pos_info_before["avg_price"] if pos_info_before else fill_price
            self._update_position(symbol, side, quantity, fill_price)
            gross_returns = (fill_price - avg_before) * min(abs(quantity), pos_info_before["quantity"] if pos_info_before else abs(quantity))

        # 5. Build order result
        order_id = f"paper-{datetime.utcnow().timestamp():.0f}"
        filled_qty = abs(quantity)
        client_payload = json.dumps(
            {
                "symbol": symbol,
                "side": side if isinstance(side, str) else side.value,
                "product": product if isinstance(product, str) else product.value,
                "order_type": order_type if isinstance(order_type, str) else order_type.value,
                "quantity": str(quantity),
                "price": str(price) if price else None,
            }
        )

        result = BrokerOrderResult(
            order_id=order_id,
            status=BrokerOrderStatus.FILLED,
            symbol=symbol,
            exchange=symbol.split(":")[0] if ":" in symbol else "NSE",
            product=product if isinstance(product, str) else product.value,
            side=side if isinstance(side, str) else side.value,
            order_type=order_type if isinstance(order_type, str) else order_type.value,
            quantity=quantity,
            price=price,
            stop_loss=stop_loss,
            target=target,
            filled_quantity=filled_qty,
            filled_price=fill_price,
            avg_price=fill_price,
            pnl=gross_returns,
        )

        # 6. Index the result
        self._order_index[order_id] = result

        # 7. Persist audit row
        await self._persist_audit(
            local_order_id=order_id,
            broker_order_id="",
            symbol=symbol,
            exchange=symbol.split(":")[0] if ":" in symbol else "NSE",
            side=side if isinstance(side, str) else side.value,
            product=product if isinstance(product, str) else product.value,
            order_type=order_type if isinstance(order_type, str) else order_type.value,
            quantity=quantity,
            price=price,
            stop_loss=stop_loss,
            target=target,
            filled_quantity=filled_qty,
            filled_price=fill_price,
            avg_price=fill_price,
            status=BrokerOrderStatus.FILLED,
            pnl=gross_returns,
            error_message=None,
            client_payload=client_payload,
        )

        return result

    # ------------------------------------------------------------------
    # Helper: validate order before fill
    # ------------------------------------------------------------------
    async def _validate_order(
        self,
        symbol: str,
        side: BrokerSide,
        product: ProductType,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal],
        stop_loss: Optional[Decimal],
        target: Optional[Decimal],
    ) -> dict[str, Any]:
        settings = get_settings()

        # Daily loss check
        quote = await self.quote(symbol)
        estimated_pnl = Decimal("0.00")
        if side == BrokerSide.SELL:
            pos_info = self._position_index.get(symbol)
            if pos_info and pos_info["quantity"] > 0:
                estimated_pnl = (quote.last_price - pos_info["avg_price"]) * abs(quantity)

        loss_check = settings.check_daily_loss(float(estimated_pnl))
        if not loss_check["allowed"]:
            return {"allowed": False, "reason": loss_check["reason"]}

        # Max open positions check
        pos_info = self._position_index.get(symbol)
        current_long = pos_info["quantity"] if pos_info else Decimal("0")
        if side == BrokerSide.BUY and current_long >= settings.max_open_positions:
            return {
                "allowed": False,
                "reason": f"Max open positions ({settings.max_open_positions}) reached for {symbol}",
            }

        # Duplicate order check (same symbol+side+date) - only blocks the
        # *same* side being placed twice in one day. Buying then selling to
        # close a position (and vice-versa) is always allowed.
        today = datetime.utcnow().strftime("%Y-%m-%d")
        recent_same_side = [
            o for o in self._order_index.values()
            if o.symbol == symbol
            and o.side == side
            and o.submitted_at.strftime("%Y-%m-%d") == today
        ]
        if recent_same_side and not getattr(self, "_allow_duplicate_orders", False):
            return {
                "allowed": False,
                "reason": f"Duplicate {side} order for {symbol} today",
            }

        # Lot / minimum check
        if quantity <= 0:
            return {"allowed": False, "reason": "Quantity must be positive"}

        return {"allowed": True, "reason": None}

    # ------------------------------------------------------------------
    # Position management (internal state)
    # ------------------------------------------------------------------
    def _update_position(self, symbol: str, side: BrokerSide, quantity: Decimal, fill_price: Decimal) -> None:
        """Add to or increase a long position."""
        pos_info = self._position_index.get(symbol)
        if side == BrokerSide.BUY:
            if pos_info is None:
                self._position_index[symbol] = {
                    "quantity": abs(quantity),
                    "avg_price": fill_price,
                    "realised_pnl": Decimal("0.00"),
                }
            else:
                old_qty = pos_info["quantity"]
                old_avg = pos_info["avg_price"]
                new_qty = old_qty + abs(quantity)
                # Weighted average price
                pos_info["avg_price"] = ((old_avg * old_qty) + (fill_price * abs(quantity))) / new_qty if new_qty > 0 else fill_price
                pos_info["quantity"] = new_qty
        elif side == BrokerSide.SELL and pos_info and pos_info["quantity"] > 0:
            # Selling reduces position; compute realised P&L
            sell_qty = min(abs(quantity), pos_info["quantity"])
            realised = (fill_price - pos_info["avg_price"]) * sell_qty
            pos_info["realised_pnl"] += realised
            pos_info["quantity"] -= sell_qty
            if pos_info["quantity"] <= 0:
                self._position_index.pop(symbol, None)

    def _close_position(self, symbol: str, quantity: Decimal) -> None:
        """Reduce a long position (possibly to zero)."""
        pos_info = self._position_index.get(symbol)
        if pos_info is None:
            return
        sell_qty = min(abs(quantity), pos_info["quantity"])
        realised = (Decimal("0") - pos_info["avg_price"]) * sell_qty  # simplified
        pos_info["quantity"] -= sell_qty
        if pos_info["quantity"] <= 0:
            self._position_index.pop(symbol, None)

    def _get_position(self, symbol: str) -> BrokerPosition:
        """Return a BrokerPosition for the given symbol."""
        pos_info = self._position_index.get(symbol)
        qty = pos_info["quantity"] if pos_info else Decimal("0")
        avg_price = pos_info["avg_price"] if pos_info else Decimal("0.00")
        realised = pos_info["realised_pnl"] if pos_info else Decimal("0.00")
        exchange = symbol.split(":")[0] if ":" in symbol else "NSE"

        return BrokerPosition(
            symbol=symbol,
            exchange=exchange,
            product=ProductType.CNC,
            quantity=qty,
            average_price=avg_price,
            market_value=qty * avg_price,
            unrealised_pnl=Decimal("0.00"),
            realised_pnl=realised,
        )

    # ------------------------------------------------------------------
    # Square off / kill switch
    # ------------------------------------------------------------------
    async def square_off(self) -> Dict[str, Any]:
        async with self._lock:
            closed_order_ids: List[str] = []
            total_pnl = Decimal("0.00")

            for symbol in list(self._position_index.keys()):
                pos_info = self._position_index.get(symbol)
                if pos_info and pos_info["quantity"] > 0:
                    result = await self._place_order_unlocked(
                        symbol,
                        BrokerSide.SELL,
                        ProductType.CNC,
                        OrderType.MARKET,
                        pos_info["quantity"],
                    )
                    if result.status == BrokerOrderStatus.FILLED:
                        closed_order_ids.append(result.order_id)
                        total_pnl += result.pnl or Decimal("0.00")

            self._position_index.clear()
            self._daily_gross_pnl = Decimal("0.00")

            return {
                "active": True,
                "closed_order_ids": closed_order_ids,
                "total_pnl": total_pnl,
                "error": None,
            }

    async def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open (non-filled) orders without touching positions."""
        async with self._lock:
            cancelled: List[str] = []
            for order_id, order in list(self._order_index.items()):
                if order.status not in (BrokerOrderStatus.FILLED, BrokerOrderStatus.CANCELLED, BrokerOrderStatus.REJECTED):
                    updated = order.model_copy(update={"status": BrokerOrderStatus.CANCELLED})
                    self._order_index[order_id] = updated
                    cancelled.append(order_id)
            return {"cancelled_order_ids": cancelled, "count": len(cancelled)}

    async def kill_switch(self) -> Dict[str, Any]:
        """Emergency stop - square off all positions and reject new entries."""
        async with self._lock:
            closed_order_ids: List[str] = []
            total_pnl = Decimal("0.00")

            for symbol in list(self._position_index.keys()):
                pos_info = self._position_index.get(symbol)
                if pos_info and pos_info["quantity"] > 0:
                    result = await self._place_order_unlocked(
                        symbol,
                        BrokerSide.SELL,
                        ProductType.CNC,
                        OrderType.MARKET,
                        pos_info["quantity"],
                    )
                    if result.status == BrokerOrderStatus.FILLED:
                        closed_order_ids.append(result.order_id)
                        total_pnl += result.pnl or Decimal("0.00")

            self._position_index.clear()
            self._daily_gross_pnl = Decimal("0.00")

            return {
                "active": len(closed_order_ids) > 0,
                "closed_order_ids": closed_order_ids,
                "total_pnl": total_pnl,
                "error": None,
            }

    # ------------------------------------------------------------------
    # Order listing / positions (required by BrokerBase)
    # ------------------------------------------------------------------
    async def orders(self, cursor: Optional[str] = None) -> BrokerOrders:
        """List tracked orders (from the in-memory index), oldest first."""
        items = [
            o for o in sorted(self._order_index.values(), key=lambda r: r.submitted_at)
        ]
        return BrokerOrders(orders=items, has_more=False, next_cursor=None)

    async def positions(self) -> List[BrokerPosition]:
        """Return all open positions."""
        return [
            self._get_position(sym)
            for sym, info in self._position_index.items()
            if info.get("quantity", Decimal("0")) > 0
        ]

    async def modify_order(
        self,
        order_id: str,
        quantity: Optional[Decimal] = None,
        price: Optional[Decimal] = None,
        stop_loss: Optional[Decimal] = None,
        target: Optional[Decimal] = None,
    ) -> BrokerOrderResult:
        """Modify an existing order (paper: mark as modified, no re-execution)."""
        existing = self._order_index.get(order_id)
        if existing is None:
            return BrokerOrderResult(
                order_id=order_id,
                status=BrokerOrderStatus.REJECTED,
                error_message="Order not found",
            )
        updated = existing.model_copy(
            update={
                "quantity": quantity or existing.quantity,
                "price": price if price is not None else existing.price,
                "stop_loss": stop_loss if stop_loss is not None else existing.stop_loss,
                "target": target if target is not None else existing.target,
            }
        )
        self._order_index[order_id] = updated
        return updated

    async def cancel_order(self, order_id: str) -> BrokerOrderResult:
        """Cancel an order (paper: only if still pending)."""
        existing = self._order_index.get(order_id)
        if existing is None:
            return BrokerOrderResult(
                order_id=order_id,
                status=BrokerOrderStatus.REJECTED,
                error_message="Order not found",
            )
        if existing.status in (BrokerOrderStatus.FILLED,):
            return BrokerOrderResult(
                order_id=order_id,
                status=BrokerOrderStatus.REJECTED,
                error_message="Order already filled - cannot cancel",
            )
        updated = existing.model_copy(update={"status": BrokerOrderStatus.CANCELLED})
        self._order_index[order_id] = updated
        return updated

    # ------------------------------------------------------------------
    # Audit persistence
    # ------------------------------------------------------------------
    async def _persist_audit(
        self,
        local_order_id: str,
        broker_order_id: str,
        symbol: str,
        exchange: str,
        side: str,
        product: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal],
        stop_loss: Optional[Decimal],
        target: Optional[Decimal],
        filled_quantity: Decimal,
        filled_price: Decimal,
        avg_price: Decimal,
        status: BrokerOrderStatus,
        pnl: Decimal,
        error_message: Optional[str],
        client_payload: str,
    ) -> None:
        """Write an immutable audit row to the SQLite audit table."""
        with sqlite3.connect(str(PAPER_BROKER_DB_PATH)) as conn:
            conn.execute(
                """
                INSERT INTO paper_order_audit
                (local_order_id, broker_order_id, symbol, exchange, side, product,
                 order_type, quantity, price, stop_loss, target, filled_quantity,
                 filled_price, avg_price, status, pnl, error_message, client_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    local_order_id,
                    broker_order_id,
                    symbol,
                    exchange,
                    side,
                    product,
                    order_type,
                    str(quantity) if quantity else "",
                    str(price) if price else "",
                    str(stop_loss) if stop_loss else "",
                    str(target) if target else "",
                    str(filled_quantity) if filled_quantity else "",
                    str(filled_price) if filled_price else "",
                    str(avg_price) if avg_price else "",
                    status,
                    str(pnl) if pnl else "",
                    error_message,
                    client_payload,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Fill-price computation
    # ------------------------------------------------------------------
    async def _compute_fill_price(
        self,
        order_type: OrderType,
        limit_price: Optional[Decimal],
        quote: BrokerQuote,
        stop_loss: Optional[Decimal],
        target: Optional[Decimal],
        side: BrokerSide = BrokerSide.BUY,
    ) -> Decimal:
        """Determine the fill price for the given order type."""
        last = quote.last_price

        if order_type == OrderType.LIMIT:
            if limit_price is None:
                return last
            band = last * Decimal("0.05")
            if side == BrokerSide.BUY and limit_price <= last + band:
                return limit_price
            if side == BrokerSide.SELL and limit_price >= last - band:
                return limit_price
            return last

        if order_type == OrderType.MARKET:
            return last

        if order_type == OrderType.SL:
            return last

        if order_type == OrderType.SL_MARKET:
            return last

        return last


# ------------------------------------------------------------------------- #
# Module-level convenience - singleton instance
# ------------------------------------------------------------------------- #

_paper_broker: PaperBroker | None = None


def get_paper_broker() -> PaperBroker:
    global _paper_broker
    if _paper_broker is None:
        _paper_broker = PaperBroker()
    return _paper_broker
