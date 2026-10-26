"""Compatibility alias for basket order service."""

from __future__ import annotations

from app.services.order_workflows import basket_order, serialize_results


class BasketOrderService:
    def __init__(self, broker=None, user_id=None):
        self.broker = broker
        self.user_id = user_id

    async def execute(self, orders=None, **kwargs):
        if self.broker is None:
            from app.brokers.factory import get_broker
            self.broker = get_broker(user_id=self.user_id)
        return await basket_order(self.broker, orders or kwargs.get("orders", []))


__all__ = ["basket_order", "BasketOrderService", "serialize_results"]
