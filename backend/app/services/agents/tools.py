"""Agent tool registry with approval-gated order tools (P5-b).

The research/orchestrator agents are read-only today, and the autopilot squad
places orders directly. This module is the single choke point every agent path
must go through when it wants to trade:

* read-only tools (``preview_order``) always run directly — no side effects;
* order-placing tools (``place_order``) check
  ``get_settings().is_approval_required`` first and, in ``REQUIRE_APPROVAL``
  mode, file a pending ``ActionCenterItem`` instead of touching the broker —
  the exact same semantics as ``POST /api/v1/orders/submit``.

Direct (PAPER) execution mirrors ``order_submit``: quote → risk check →
``broker.place_order`` → persist an ``Order`` row. Nothing here bypasses the
risk engine, and ``LIVE_ENABLED`` routing stays inside the broker factory.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.logging import get_logger

logger = get_logger("agents.tools")


class AgentToolError(ValueError):
    """Raised when an agent tool call is invalid or fails a guard (mirrors HTTP 422)."""


# Tools whose invocation may place/cancel real or paper orders. Every name in
# this set is approval-gated; anything else in the registry is read-only.
ORDER_TOOL_NAMES = frozenset({"place_order"})


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "preview_order": {
        "description": "Read-only order preview: live quote + risk check, no side effects.",
        "parameters": {
            "symbol": {"type": "string", "description": "e.g. NSE:RELIANCE"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "quantity": {"type": "number", "minimum": 1},
        },
        "required": ["symbol", "side", "quantity"],
        "side_effects": False,
    },
    "place_order": {
        "description": (
            "Place an order. In REQUIRE_APPROVAL mode this files a pending "
            "Action Center item for a human instead of filling."
        ),
        "parameters": {
            "symbol": {"type": "string", "description": "e.g. NSE:RELIANCE"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "quantity": {"type": "number", "minimum": 1},
            "price": {"type": "number", "description": "Limit price; omit for market"},
            "order_type": {"type": "string", "default": "MARKET"},
        },
        "required": ["symbol", "side", "quantity"],
        "side_effects": True,
    },
}


def list_tools() -> list[dict[str, Any]]:
    """Return the registry as name + schema dicts (for agent prompts / UI)."""
    return [{"name": name, **schema} for name, schema in TOOL_SCHEMAS.items()]


def is_order_tool(name: str) -> bool:
    return name in ORDER_TOOL_NAMES


def _validate_order_args(args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args.get("symbol") or "").strip().upper()
    if not symbol:
        raise AgentToolError("symbol is required")
    try:
        from app.services.data.providers import parse_symbol

        parse_symbol(symbol)
    except Exception as exc:
        raise AgentToolError(f"Invalid symbol '{symbol}': {exc}") from exc

    side = str(args.get("side") or "").strip().upper()
    if side not in ("BUY", "SELL"):
        raise AgentToolError(f"side must be BUY or SELL, got '{args.get('side')}'")

    try:
        quantity = Decimal(str(args.get("quantity")))
    except (TypeError, ArithmeticError, ValueError) as exc:
        raise AgentToolError(f"quantity must be a positive number: {exc}") from exc
    if quantity <= 0:
        raise AgentToolError("quantity must be positive")

    price = args.get("price")
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError) as exc:
            raise AgentToolError(f"price must be a number: {exc}") from exc

    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "order_type": str(args.get("order_type") or "MARKET").upper(),
    }


async def _queue_approval(user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """File a pending ActionCenterItem — no broker contact (mirrors order_submit)."""
    from app.db.models import ActionCenterItem
    from app.db.session import SessionFactory

    async with SessionFactory() as session:
        item = ActionCenterItem(
            user_id=user_id,
            symbol=fields["symbol"],
            side=fields["side"],
            quantity=str(fields["quantity"]),
            price=float(fields["price"]) if fields["price"] is not None else 0.0,
            status="pending",
            order_type=fields["order_type"],
            payload=None,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        logger.info("agent tool place_order queued for approval: %s %s", item.id, fields["symbol"])
        return {
            "id": item.id,
            "status": "pending_approval",
            "message": "Order queued for approval in Action Center",
        }


async def _execute_direct(user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """PAPER/LIVE direct execution — mirrors POST /api/v1/orders/submit."""
    from sqlalchemy import insert

    from app.brokers.factory import get_broker
    from app.brokers.interface import BrokerSide, OrderType, ProductType
    from app.core.config import get_settings
    from app.db.models import Order as OrderModel
    from app.db.session import SessionFactory

    broker = get_broker(name=getattr(get_settings(), "selected_execution_broker", None), user_id=user_id)

    try:
        quote = await broker.quote(fields["symbol"])
        price_for_risk = float(quote.last_price)
    except Exception:
        price_for_risk = float(fields["price"]) if fields["price"] else 0.0
    if price_for_risk > 0:
        from app.services.risk.risk_engine import RiskEngine

        risk_ok, risk_notes = RiskEngine.check_order(
            symbol=fields["symbol"],
            quantity=fields["quantity"],
            side=fields["side"],
            entry_price=Decimal(str(price_for_risk)),
        )
        if not risk_ok:
            raise AgentToolError(f"Risk check failed: {risk_notes}")

    result = await broker.place_order(
        symbol=fields["symbol"],
        side=BrokerSide(fields["side"]),
        product=ProductType.CNC,
        order_type=OrderType(fields["order_type"]),
        quantity=fields["quantity"],
        price=Decimal(str(fields["price"])) if fields["price"] is not None else None,
    )
    if result.status in ("rejected", "cancelled"):
        raise AgentToolError(result.error_message or "Order submission failed")

    async with SessionFactory() as session:
        row = await session.execute(
            insert(OrderModel)
            .values(
                user_id=user_id,
                symbol=fields["symbol"],
                side=fields["side"],
                quantity=str(fields["quantity"]),
                price=float(result.filled_price or fields["price"] or 0),
                status="filled",
                order_type=fields["order_type"],
                extra_data=result.order_id,
            )
            .returning(OrderModel.id)
        )
        db_order_id = row.scalar_one()
        await session.commit()

    logger.info("agent tool place_order filled: %s %s", result.order_id, fields["symbol"])
    return {
        "id": db_order_id,
        "order_id": result.order_id,
        "symbol": fields["symbol"],
        "side": fields["side"],
        "quantity": float(fields["quantity"]),
        "fill_price": float(result.filled_price) if result.filled_price else None,
        "status": "filled",
        "message": "Order submitted (agent tool)",
    }


async def _preview(user_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Read-only preview: live quote + risk check. Never gated, never fills."""
    from app.brokers.factory import get_broker
    from app.core.config import get_settings

    fields = _validate_order_args(args)
    broker = get_broker(name=getattr(get_settings(), "selected_execution_broker", None), user_id=user_id)
    try:
        quote = await broker.quote(fields["symbol"])
        price = float(quote.last_price)
    except Exception as exc:
        raise AgentToolError(f"Could not fetch quote for '{fields['symbol']}': {exc}") from exc
    if price <= 0:
        raise AgentToolError(f"No price data for '{fields['symbol']}'")

    risk_notes: str | None = None
    from app.services.risk.risk_engine import RiskEngine

    risk_ok, risk_notes = RiskEngine.check_order(
        symbol=fields["symbol"],
        quantity=fields["quantity"],
        side=fields["side"],
        entry_price=Decimal(str(price)),
    )
    if not risk_ok:
        raise AgentToolError(f"Risk check failed: {risk_notes}")

    return {
        "symbol": fields["symbol"],
        "side": fields["side"],
        "quantity": float(fields["quantity"]),
        "price": price,
        "estimated_fill": price,
        "status": "preview",
        "risk_notes": risk_notes,
    }


async def run_tool(name: str, args: dict[str, Any] | None, *, user_id: str) -> dict[str, Any]:
    """Run one agent tool call for ``user_id``.

    Order-placing tools are approval-gated: in ``REQUIRE_APPROVAL`` mode they
    return ``{"status": "pending_approval", ...}`` without contacting the
    broker. Unknown tool names raise :class:`AgentToolError`.
    """
    from app.core.config import get_settings

    args = dict(args or {})
    if name == "preview_order":
        return await _preview(user_id, args)
    if name == "place_order":
        fields = _validate_order_args(args)
        if getattr(get_settings(), "is_approval_required", False):
            return await _queue_approval(user_id, fields)
        return await _execute_direct(user_id, fields)
    raise AgentToolError(f"Unknown tool '{name}'. Available: {sorted(TOOL_SCHEMAS)}")
