"""Zerodha Kite Connect broker adapter (disabled until fully configured)."""
from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.brokers.interface import (
    BrokerBase,
    BrokerConnectRequest,
    BrokerConnectResponse,
    BrokerFunds,
    BrokerOrderResult,
    BrokerOrderStatus,
    BrokerQuote,
    BrokerPosition,
    BrokerOrders,
    BrokerSide,
    ProductType,
    OrderType,
)
from app.core.config import get_settings


class ZerodhaBroker(BrokerBase):
    """Zerodha Kite Connect broker adapter - DISABLED until LIVE_ENABLED + credentials."""
    name: str = "zerodha"

    async def connect(self, credentials: BrokerConnectRequest) -> BrokerConnectResponse:
        settings = get_settings()
        if not settings.is_live:
            return BrokerConnectResponse(
                authenticated=False,
                access_token=None,
                expires_at=None,
                message="Zerodha Kite Connect is disabled. Set execution_mode=LIVE_ENABLED and configure credentials.",
            )
        return BrokerConnectResponse(
            authenticated=False,
            access_token=None,
            expires_at=None,
            message="Zerodha connection pending - configure API keys in the Brokers page.",
        )

    async def connection_status(self) -> Dict[str, Any]:
        settings = get_settings()
        if settings.is_live:
            return {"online": False, "broker_name": self.name, "last_checked": datetime.utcnow(), "error": "LIVE_ENABLED but credentials not configured"}
        return {"online": False, "broker_name": self.name, "last_checked": datetime.utcnow(), "error": "Disabled in paper mode."}

    async def funds(self) -> BrokerFunds:
        return BrokerFunds(cash=Decimal("0.00"), margin_available=Decimal("0.00"), equity=Decimal("0.00"))

    async def quote(self, symbol: str) -> BrokerQuote:
        return BrokerQuote(symbol=symbol, exchange=symbol.split(":")[0] if ":" in symbol else "NSE", last_price=Decimal("0.00"), bid=Decimal("0.00"), ask=Decimal("0.00"), volume=0, open=Decimal("0.00"), high=Decimal("0.00"), low=Decimal("0.00"), close=Decimal("0.00"), timestamp=datetime.utcnow())

    async def place_order(self, symbol: str, side: BrokerSide, product: ProductType, order_type: OrderType, quantity: Decimal, price: Optional[Decimal] = None, stop_loss: Optional[Decimal] = None, target: Optional[Decimal] = None) -> BrokerOrderResult:
        return BrokerOrderResult(order_id="", status=BrokerOrderStatus.REJECTED, symbol=symbol, exchange=symbol.split(":")[0] if ":" in symbol else "NSE", product=product, order_type=order_type, quantity=quantity, price=price, stop_loss=stop_loss, target=target, error_message="Zerodha broker disabled. Set LIVE_ENABLED and configure credentials.")

    async def modify_order(self, order_id: str, quantity: Optional[Decimal] = None, price: Optional[Decimal] = None, stop_loss: Optional[Decimal] = None, target: Optional[Decimal] = None) -> BrokerOrderResult:
        return BrokerOrderResult(order_id=order_id, status=BrokerOrderStatus.REJECTED, symbol="", exchange="", product=ProductType.CNC, order_type=OrderType.MARKET, quantity=quantity or Decimal("0"), price=price, stop_loss=stop_loss, target=target, error_message="Zerodha broker disabled.")

    async def cancel_order(self, order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult(order_id=order_id, status=BrokerOrderStatus.CANCELLED, symbol="", exchange="", product=ProductType.CNC, order_type=OrderType.MARKET, quantity=Decimal("0"), price=Decimal("0.00"), stop_loss=Decimal("0.00"), target=Decimal("0.00"), error_message="Zerodha broker disabled.")

    async def orders(self, cursor: Optional[str] = None) -> BrokerOrders:
        return BrokerOrders(orders=[], has_more=False, next_cursor=None)

    async def positions(self) -> List[BrokerPosition]:
        return []

    async def square_off(self) -> Dict[str, Any]:
        return {"active": False, "closed_order_ids": [], "total_pnl": Decimal("0.00"), "error": "Zerodha broker disabled."}

    async def kill_switch(self) -> Dict[str, Any]:
        return {"active": False, "closed_order_ids": [], "total_pnl": Decimal("0.00"), "error": "Zerodha broker disabled."}
