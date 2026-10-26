"""Tests for broker plugin loading, factory, and master contract sync/import."""

from __future__ import annotations

import pytest

from app.brokers.plugin_loader import (
    list_plugin_names,
    list_plugins,
    load_plugin_metadata,
    load_broker_class,
    plugin_supports,
)
from app.brokers.factory import get_broker, create_broker, BrokerFactory, broker_factory
from app.brokers.paper import PaperBroker
from app.brokers.zerodha import ZerodhaBroker
from app.brokers.angelone import AngelOneBroker


# ---- Plugin metadata ----


def test_list_plugin_names_contains_all():
    names = list_plugin_names()
    assert "paper" in names
    assert "zerodha" in names
    assert "angelone" in names


def test_list_plugins_returns_metadata():
    plugins = list_plugins()
    assert isinstance(plugins, list)
    assert len(plugins) >= 3
    names = {p["name"] for p in plugins}
    assert {"paper", "zerodha", "angelone"}.issubset(names)


def test_load_plugin_metadata_paper():
    meta = load_plugin_metadata("paper")
    assert meta["name"] == "paper"
    assert meta["module"].startswith("app.brokers.paper")
    assert meta["class"] == "PaperBroker"
    assert meta["auth_required"] is False


def test_load_broker_class():
    assert load_broker_class("paper") is PaperBroker
    assert load_broker_class("zerodha") is ZerodhaBroker
    assert load_broker_class("angelone") is AngelOneBroker


def test_plugin_supports():
    assert plugin_supports("paper", "orders") is True
    assert plugin_supports("paper", "nonexistent-cap") is False
    assert plugin_supports("zerodha", "gtt") is True


def test_load_unknown_plugin_raises():
    with pytest.raises(FileNotFoundError):
        load_plugin_metadata("no-such-broker")
    with pytest.raises(FileNotFoundError):
        load_broker_class("no-such-broker")


# ---- Factory ----


def test_factory_returns_paper_by_default():
    broker = get_broker()
    assert isinstance(broker, PaperBroker)


def test_factory_selects_by_name():
    assert isinstance(get_broker("paper"), PaperBroker)
    assert isinstance(get_broker("zerodha"), ZerodhaBroker)
    assert isinstance(get_broker("angelone"), AngelOneBroker)


def test_factory_aliases():
    assert isinstance(create_broker("paper"), PaperBroker)
    bf = BrokerFactory()
    assert isinstance(bf.create("paper"), PaperBroker)
    assert isinstance(broker_factory.get("paper"), PaperBroker)


# ---- Master contract sync/import ----


@pytest.mark.asyncio
async def test_master_contract_sync_and_import():
    import asyncio
    from app.db.base import Base
    from app.db.session import engine, SessionFactory

    import app.db.models  # noqa: F401
    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    await _init()
    from app.services.master_contract import sync_contracts, import_contracts, import_csv, list_contracts

    async with SessionFactory() as session:
        res = await sync_contracts(
            session,
            "paper",
            [{"symbol": "RELIANCE", "exchange": "NSE", "lot_size": 1}],
        )
        assert res["created"] >= 1 or res["updated"] >= 1

        rows = await list_contracts(session, q="RELIANCE", broker="paper")
        assert any(r["symbol"] == "RELIANCE" for r in rows)

        res2 = await import_contracts(
            session,
            [{"symbol": "TCS", "exchange": "NSE", "lot_size": 1}],
            broker="paper",
        )
        assert res2["imported"] >= 1

        csv_text = "symbol,exchange,lot_size\nINFY,NSE,1\n"
        res3 = await import_csv(session, csv_text, broker="paper")
        assert res3["imported"] >= 1
