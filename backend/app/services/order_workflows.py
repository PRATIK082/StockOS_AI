"""Smart, basket and split order workflows for StockOS.

These helpers wrap the broker adapter's ``place_order`` primitive and add
higher-level orchestration: best-price chasing, multi-leg baskets and
chunked splitting of large orders.  They are used by the orders router and
by the Action Center execution path.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.brokers.interface import BrokerSide, ProductType, OrderType
from app.core.config import get_settings


def _side(v: Any) -> BrokerSide:
    return BrokerSide(str(v).upper())


def _order_type(v: Any) -> OrderType:
    v = (v or "MARKET").upper()
    if v in ("LIMIT",):
        return OrderType.LIMIT
    if v in ("SL", "SL-M", "SL_MARKET"):
        return OrderType.SL if v == "SL" else OrderType.SL_MARKET
    return OrderType.MARKET


async def smart_order(
    broker: Any,
    *,
    symbol: str,
    side: Any,
    quantity: Any,
    price: Optional[Any] = None,
    order_type: Optional[str] = None,
    chase: bool = False,
    position_size: Optional[Any] = None,
    stop_loss: Optional[Any] = None,
    target: Optional[Any] = None,
) -> List[Any]:
    """Place a single smart order.

    When ``chase`` is true (or no price is given for a market order) the
    best bid/ask from the broker quote is used.  When ``position_size`` is
    provided the order quantity is adjusted to reach that target position.
    """
    symbol = str(symbol).strip().upper()
    qty = Decimal(str(quantity))
    side_obj = _side(side)

    if position_size is not None:
        positions = await broker.positions()
        current = Decimal("0")
        for pos in positions:
            if getattr(pos, "symbol", None) == symbol:
                current = Decimal(str(getattr(pos, "quantity", 0)))
                break
        delta = Decimal(str(position_size)) - current
        if delta == 0:
            return []
        side_obj = BrokerSide.BUY if delta > 0 else BrokerSide.SELL
        qty = abs(delta)

    resolved_type = order_type or ("LIMIT" if price is not None else "MARKET")
    resolved_price = Decimal(str(price)) if price is not None else None

    if chase or resolved_price is None:
        try:
            quote = await broker.quote(symbol)
            if side_obj == BrokerSide.BUY:
                resolved_price = Decimal(str(getattr(quote, "ask", getattr(quote, "last_price", 0))))
            else:
                resolved_price = Decimal(str(getattr(quote, "bid", getattr(quote, "last_price", 0))))
            if resolved_price and resolved_price > 0:
                resolved_type = "LIMIT"
        except Exception:
            pass

    result = await broker.place_order(
        symbol=symbol,
        side=side_obj,
        product=ProductType.CNC,
        order_type=_order_type(resolved_type),
        quantity=qty,
        price=resolved_price,
        stop_loss=Decimal(str(stop_loss)) if stop_loss is not None else None,
        target=Decimal(str(target)) if target is not None else None,
    )
    return [result]


async def basket_order(broker: Any, orders: List[Dict[str, Any]]) -> List[Any]:
    """Place a basket of orders sequentially."""
    results: List[Any] = []
    prev = getattr(broker, "_allow_duplicate_orders", False)
    try:
        broker._allow_duplicate_orders = True
        for o in orders or []:
            symbol = str(o.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            side = o.get("side", "BUY")
            quantity = o.get("quantity", 0)
            price = o.get("price", None)
            order_type = o.get("order_type", o.get("orderType", "MARKET"))
            res_list = await smart_order(
                broker,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                order_type=order_type,
                chase=bool(o.get("chase", False)),
                position_size=o.get("position_size", None),
                stop_loss=o.get("stop_loss", None),
                target=o.get("target", None),
            )
            results.extend(res_list)
    finally:
        broker._allow_duplicate_orders = prev
    return results


async def split_order(
    broker: Any,
    *,
    symbol: str,
    side: Any,
    quantity: Any,
    splits: Optional[int] = None,
    split_size: Optional[Any] = None,
    chunk_size: Optional[Any] = None,
    price: Optional[Any] = None,
    order_type: Optional[str] = None,
    chase: bool = False,
) -> List[Any]:
    """Split a large order into multiple smaller orders."""
    symbol = str(symbol).strip().upper()
    total = Decimal(str(quantity))
    if total <= 0:
        return []

    if chunk_size is not None:
        chunk = Decimal(str(chunk_size))
    elif split_size is not None:
        chunk = Decimal(str(split_size))
    elif splits and int(splits) > 0:
        import math
        chunk = (total / Decimal(int(splits))).quantize(Decimal("0.01"))
    else:
        splits = 2
        chunk = (total / Decimal(2)).quantize(Decimal("0.01"))

    if chunk <= 0:
        chunk = total

    num_chunks = int((total + chunk - Decimal("1")) // chunk) if chunk > 0 else 1
    if num_chunks < 1:
        num_chunks = 1

    results: List[Any] = []
    remaining = total
    prev = getattr(broker, "_allow_duplicate_orders", False)
    try:
        broker._allow_duplicate_orders = True
        for _ in range(num_chunks):
            if remaining <= 0:
                break
            q = chunk if remaining >= chunk else remaining
            remaining -= q
            res_list = await smart_order(
                broker,
                symbol=symbol,
                side=side,
                quantity=q,
                price=price,
                order_type=order_type,
                chase=chase,
            )
            results.extend(res_list)
    finally:
        broker._allow_duplicate_orders = prev
    return results


def serialize_results(results: List[Any]) -> List[Dict[str, Any]]:
    out = []
    for r in results:
        out.append({
            "order_id": getattr(r, "order_id", None),
            "status": getattr(r, "status", None),
            "symbol": getattr(r, "symbol", None),
            "side": getattr(r, "side", None),
            "quantity": str(getattr(r, "quantity", "")),
            "filled_quantity": str(getattr(r, "filled_quantity", "")),
            "filled_price": float(getattr(r, "filled_price", 0) or 0),
            "error_message": getattr(r, "error_message", None),
        })
    return out


def spec_for_approval(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": kind, "payload": payload}


def parse_approval_payload(item: Any) -> Dict[str, Any]:
    raw = getattr(item, "payload", None)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}
