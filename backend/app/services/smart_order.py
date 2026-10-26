"""Compatibility alias for smart order service."""

from __future__ import annotations

from app.services.order_workflows import smart_order, serialize_results


class SmartOrderService:
    def __init__(self, broker=None, user_id=None):
        self.broker = broker
        self.user_id = user_id

    async def execute(self, **kwargs):
        if self.broker is None:
            from app.brokers.factory import get_broker
            self.broker = get_broker(user_id=self.user_id)
        return await smart_order(self.broker, **kwargs)


__all__ = ["smart_order", "SmartOrderService", "serialize_results"]
