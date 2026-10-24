"""Tests for Zerodha and AngelOne broker stubs.

These stubs reject all orders when execution_mode != LIVE_ENABLED.
Tests verify the disabled-by-default behaviour and that they implement
the full BrokerBase interface.
"""

from __future__ import annotations

import pytest
import asyncio
from decimal import Decimal

from app.brokers.zerodha import ZerodhaBroker
from app.brokers.angelone import AngelOneBroker
from app.brokers.interface import (
    BrokerBase,
    BrokerConnectRequest,
    BrokerConnectResponse,
    BrokerFunds,
    BrokerOrderResult,
    BrokerOrders,
    BrokerPosition,
    BrokerSide,
    OrderType,
    ProductType,
    BrokerOrderStatus,
)
from app.core.config import get_settings


# ---- Interface compliance ----


def test_zerodha_is_broker_base():
    assert issubclass(ZerodhaBroker, BrokerBase)


def test_angelone_is_broker_base():
    assert issubclass(AngelOneBroker, BrokerBase)


def test_zerodha_name():
    assert ZerodhaBroker().name == "zerodha"


def test_angelone_name():
    assert AngelOneBroker().name == "angelone"


# ---- Zerodha stub ----


@pytest.mark.asyncio
async def test_zerodha_connect_rejected_in_paper_mode():
    settings = get_settings()
    original_mode = settings.execution_mode
    settings.execution_mode = "PAPER"
    try:
        broker = ZerodhaBroker()
        creds = BrokerConnectRequest(api_key="fake", api_secret="fake")
        resp = await broker.connect(creds)
        assert resp.authenticated is False
        assert "disabled" in resp.message.lower() or "paper" in resp.message.lower()
    finally:
        settings.execution_mode = original_mode


@pytest.mark.asyncio
async def test_zerodha_place_order_rejected():
    broker = ZerodhaBroker()
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    assert result.status == BrokerOrderStatus.REJECTED
    assert "disabled" in result.error_message.lower()


@pytest.mark.asyncio
async def test_zerodha_modify_order_rejected():
    broker = ZerodhaBroker()
    result = await broker.modify_order("fake-id", price=Decimal("100"))
    assert result.status == BrokerOrderStatus.REJECTED


@pytest.mark.asyncio
async def test_zerodha_cancel_order():
    broker = ZerodhaBroker()
    result = await broker.cancel_order("fake-id")
    assert result.status == BrokerOrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_zerodha_orders_empty():
    broker = ZerodhaBroker()
    result = await broker.orders()
    assert isinstance(result, BrokerOrders)
    assert result.orders == []


@pytest.mark.asyncio
async def test_zerodha_positions_empty():
    broker = ZerodhaBroker()
    result = await broker.positions()
    assert result == []


@pytest.mark.asyncio
async def test_zerodha_funds_zero():
    broker = ZerodhaBroker()
    funds = await broker.funds()
    assert funds.cash == Decimal("0.00")
    assert funds.margin_available == Decimal("0.00")


@pytest.mark.asyncio
async def test_zerodha_connection_status():
    broker = ZerodhaBroker()
    status = await broker.connection_status()
    assert status["online"] is False
    assert status["broker_name"] == "zerodha"
    assert status["error"] is not None


@pytest.mark.asyncio
async def test_zerodha_square_off_disabled():
    broker = ZerodhaBroker()
    result = await broker.square_off()
    assert result["active"] is False
    assert "disabled" in result["error"].lower()


@pytest.mark.asyncio
async def test_zerodha_kill_switch_disabled():
    broker = ZerodhaBroker()
    result = await broker.kill_switch()
    assert result["active"] is False
    assert "disabled" in result["error"].lower()


@pytest.mark.asyncio
async def test_zerodha_quote_zero():
    broker = ZerodhaBroker()
    q = await broker.quote("NSE:RELIANCE")
    assert q.last_price == Decimal("0.00")


# ---- AngelOne stub ----


@pytest.mark.asyncio
async def test_angelone_connect_rejected_in_paper_mode():
    settings = get_settings()
    original_mode = settings.execution_mode
    settings.execution_mode = "PAPER"
    try:
        broker = AngelOneBroker()
        creds = BrokerConnectRequest(api_key="fake", api_secret="fake")
        resp = await broker.connect(creds)
        assert resp.authenticated is False
        assert "disabled" in resp.message.lower() or "paper" in resp.message.lower()
    finally:
        settings.execution_mode = original_mode


@pytest.mark.asyncio
async def test_angelone_place_order_rejected():
    broker = AngelOneBroker()
    result = await broker.place_order(
        symbol="NSE:RELIANCE",
        side=BrokerSide.BUY,
        product=ProductType.CNC,
        order_type=OrderType.MARKET,
        quantity=Decimal("10"),
    )
    assert result.status == BrokerOrderStatus.REJECTED
    assert "disabled" in result.error_message.lower()


@pytest.mark.asyncio
async def test_angelone_modify_order_rejected():
    broker = AngelOneBroker()
    result = await broker.modify_order("fake-id", price=Decimal("100"))
    assert result.status == BrokerOrderStatus.REJECTED


@pytest.mark.asyncio
async def test_angelone_cancel_order():
    broker = AngelOneBroker()
    result = await broker.cancel_order("fake-id")
    assert result.status == BrokerOrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_angelone_orders_empty():
    broker = AngelOneBroker()
    result = await broker.orders()
    assert result.orders == []


@pytest.mark.asyncio
async def test_angelone_positions_empty():
    broker = AngelOneBroker()
    result = await broker.positions()
    assert result == []


@pytest.mark.asyncio
async def test_angelone_funds_zero():
    broker = AngelOneBroker()
    funds = await broker.funds()
    assert funds.cash == Decimal("0.00")


@pytest.mark.asyncio
async def test_angelone_connection_status():
    broker = AngelOneBroker()
    status = await broker.connection_status()
    assert status["online"] is False
    assert status["broker_name"] == "angelone"


@pytest.mark.asyncio
async def test_angelone_square_off_disabled():
    broker = AngelOneBroker()
    result = await broker.square_off()
    assert result["active"] is False
    assert "disabled" in result["error"].lower()


@pytest.mark.asyncio
async def test_angelone_kill_switch_disabled():
    broker = AngelOneBroker()
    result = await broker.kill_switch()
    assert result["active"] is False
    assert "disabled" in result["error"].lower()


@pytest.mark.asyncio
async def test_angelone_quote_zero():
    broker = AngelOneBroker()
    q = await broker.quote("NSE:TCS")
    assert q.last_price == Decimal("0.00")


# ---- LIVE mode still rejects (credentials not configured) ----


@pytest.mark.asyncio
async def test_zerodha_live_mode_still_rejected_without_creds():
    settings = get_settings()
    original_mode = settings.execution_mode
    settings.execution_mode = "LIVE_ENABLED"
    try:
        broker = ZerodhaBroker()
        result = await broker.place_order(
            symbol="NSE:RELIANCE",
            side=BrokerSide.BUY,
            product=ProductType.CNC,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        assert result.status == BrokerOrderStatus.REJECTED
        assert "credentials" in result.error_message.lower() or "configure" in result.error_message.lower()
    finally:
        settings.execution_mode = original_mode


@pytest.mark.asyncio
async def test_angelone_live_mode_still_rejected_without_creds():
    settings = get_settings()
    original_mode = settings.execution_mode
    settings.execution_mode = "LIVE_ENABLED"
    try:
        broker = AngelOneBroker()
        result = await broker.place_order(
            symbol="NSE:RELIANCE",
            side=BrokerSide.BUY,
            product=ProductType.CNC,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )
        assert result.status == BrokerOrderStatus.REJECTED
        assert "credentials" in result.error_message.lower() or "configure" in result.error_message.lower()
    finally:
        settings.execution_mode = original_mode
