"""Unit tests for PaperBroker: fills, positions, P&L, square-off, kill-switch."""

from __future__ import annotations

import pytest
import asyncio
from decimal import Decimal
from datetime import datetime

from app.brokers.paper import PaperBroker
from app.brokers.interface import (
    BrokerConnectRequest,
    BrokerSide,
    OrderType,
    ProductType,
    BrokerOrderStatus,
)


@pytest.fixture
def broker():
    """Fresh PaperBroker with reset state."""
    b = PaperBroker(user_id="test-user")
    b._position_index.clear()
    b._order_index.clear()
    b._daily_gross_pnl = Decimal("0.00")
    return b


@pytest.fixture
def mock_quote(monkeypatch):
    """Patch PaperBroker.quote to avoid external data calls."""

    async def fake_quote(self_inner, symbol):
        from app.brokers.interface import BrokerQuote

        return BrokerQuote(
            symbol=symbol,
            exchange=symbol.split(":")[0] if ":" in symbol else "NSE",
            last_price=Decimal("1500.00"),
            bid=Decimal("1499.00"),
            ask=Decimal("1501.00"),
            volume=100000,
            open=Decimal("1490.00"),
            high=Decimal("1510.00"),
            low=Decimal("1485.00"),
            close=Decimal("1495.00"),
            timestamp=datetime.utcnow(),
        )

    monkeypatch.setattr(PaperBroker, "quote", fake_quote)


# ---- Connection ----


@pytest.mark.asyncio
async def test_connect_always_succeeds(broker):
    creds = BrokerConnectRequest(api_key="fake", api_secret="fake")
    resp = await broker.connect(creds)
    assert resp.authenticated is True
    assert resp.access_token is None


@pytest.mark.asyncio
async def test_connection_status_online(broker):
    status = await broker.connection_status()
    assert status["online"] is True
    assert status["broker_name"] == "paper"
    assert status["error"] is None


# ---- Funds ----


@pytest.mark.asyncio
async def test_funds_returns_positive(broker):
    funds = await broker.funds()
    assert funds.cash > 0
    assert funds.margin_available > 0
    assert funds.equity > 0


# ---- Place order (buy) ----


@pytest.mark.asyncio
async def test_buy_order_fills(broker, mock_quote):
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    assert result.status == BrokerOrderStatus.FILLED
    assert result.symbol == "NSE:RELIANCE"
    assert result.filled_price == Decimal("1500.00")
    assert result.filled_quantity == Decimal("10")
    assert result.order_id.startswith("paper-")


@pytest.mark.asyncio
async def test_buy_creates_position(broker, mock_quote):
    await broker.place_order(
        symbol="NSE:TCS",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )
    positions = await broker.positions()
    assert len(positions) == 1
    assert positions[0].symbol == "NSE:TCS"
    assert positions[0].quantity == Decimal("5")


@pytest.mark.asyncio
async def test_duplicate_same_side_blocks_second_buy(broker, mock_quote):
    """Duplicate same-side check prevents two BUYs for the same symbol in one day."""
    await broker.place_order(
        symbol="NSE:INFY",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("3"),
    )
    result = await broker.place_order(
        symbol="NSE:INFY",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("7"),
    )
    assert result.status == BrokerOrderStatus.REJECTED
    # Original position unchanged
    positions = await broker.positions()
    assert len(positions) == 1
    assert positions[0].quantity == Decimal("3")


# ---- Place order (sell) ----


@pytest.mark.asyncio
async def test_sell_reduces_position(broker, mock_quote):
    # Buy first
    await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    # Sell half
    await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.SELL,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )
    positions = await broker.positions()
    assert len(positions) == 1
    assert positions[0].quantity == Decimal("5")


@pytest.mark.asyncio
async def test_sell_full_closes_position(broker, mock_quote):
    await broker.place_order(
        symbol="NSE:TCS",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    result = await broker.place_order(
        symbol="NSE:TCS",
        side=BrokerSide.SELL,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    assert result.status == BrokerOrderStatus.FILLED
    positions = await broker.positions()
    assert len(positions) == 0


# ---- Duplicate order check ----


@pytest.mark.asyncio
async def test_duplicate_same_side_rejected(broker, mock_quote):
    await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )
    assert result.status == BrokerOrderStatus.REJECTED
    assert "Duplicate" in result.error_message


@pytest.mark.asyncio
async def test_opposite_side_allowed(broker, mock_quote):
    """Buying then selling the same symbol is allowed (not a duplicate)."""
    await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.SELL,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )
    assert result.status == BrokerOrderStatus.FILLED


# ---- Validation ----


@pytest.mark.asyncio
async def test_zero_quantity_rejected(broker, mock_quote):
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("0"),
    )
    assert result.status == BrokerOrderStatus.REJECTED
    assert "positive" in result.error_message.lower()


@pytest.mark.asyncio
async def test_negative_quantity_rejected(broker, mock_quote):
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("-5"),
    )
    assert result.status == BrokerOrderStatus.REJECTED


# ---- Orders listing ----


@pytest.mark.asyncio
async def test_orders_list_returns_placed(broker, mock_quote):
    await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    orders_resp = await broker.orders()
    assert len(orders_resp.orders) >= 1
    assert orders_resp.orders[0].symbol == "NSE:RELIANCE"


# ---- Modify / Cancel ----


@pytest.mark.asyncio
async def test_cancel_filled_order_rejected(broker, mock_quote):
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    cancel = await broker.cancel_order(result.order_id)
    assert cancel.status == BrokerOrderStatus.REJECTED
    assert "filled" in cancel.error_message.lower()


@pytest.mark.asyncio
async def test_modify_order(broker, mock_quote):
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    modified = await broker.modify_order(result.order_id, price=Decimal("1550.00"))
    assert modified.price == Decimal("1550.00")


@pytest.mark.asyncio
async def test_modify_nonexistent_order(broker):
    modified = await broker.modify_order("nonexistent-id", price=Decimal("100"))
    assert modified.status == BrokerOrderStatus.REJECTED


@pytest.mark.asyncio
async def test_cancel_nonexistent_order(broker):
    cancel = await broker.cancel_order("nonexistent-id")
    assert cancel.status == BrokerOrderStatus.REJECTED


# ---- Square off ----


@pytest.mark.asyncio
async def test_square_off_closes_all(broker, mock_quote):
    # Open two positions
    await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    # Use a different symbol for second buy (duplicate check)
    await broker.place_order(
        symbol="NSE:TCS",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )

    result = await broker.square_off()
    assert result["closed_order_ids"] is not None
    assert len(result["closed_order_ids"]) == 2

    positions = await broker.positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_square_off_empty(broker, mock_quote):
    result = await broker.square_off()
    assert result["closed_order_ids"] == []


# ---- Kill switch ----


@pytest.mark.asyncio
async def test_kill_switch(broker, mock_quote):
    await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )

    result = await broker.kill_switch()
    assert result["active"] is True
    assert len(result["closed_order_ids"]) >= 1
    positions = await broker.positions()
    assert len(positions) == 0


# ---- Fill price computation ----


@pytest.mark.asyncio
async def test_limit_order_fills_at_limit(broker, mock_quote):
    """Limit buy within 5% of last price fills at the limit price."""
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("1490.00"),
    )
    assert result.status == BrokerOrderStatus.FILLED
    assert result.filled_price == Decimal("1490.00")


@pytest.mark.asyncio
async def test_limit_order_far_from_market_fills_at_last(broker, mock_quote):
    """Limit buy far above market fills at last price (within band)."""
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("2000.00"),  # > 5% above 1500
    )
    assert result.status == BrokerOrderStatus.FILLED
    assert result.filled_price == Decimal("1500.00")
