"""Master contract sync/import helpers."""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MasterContract


def _normalize(item: dict, broker: Optional[str] = None) -> dict:
    return {
        "symbol": str(item.get("symbol", "")).upper(),
        "exchange": str(item.get("exchange", "NSE")).upper(),
        "instrument_type": str(item.get("instrument_type", "EQUITY")).upper(),
        "underlying": item.get("underlying"),
        "expiry": item.get("expiry"),
        "strike": item.get("strike"),
        "lot_size": int(item.get("lot_size", 1) or 1),
        "broker": item.get("broker", broker),
    }


async def import_contracts(
    session: AsyncSession,
    contracts: Iterable[dict],
    broker: Optional[str] = None,
) -> dict:
    """Import a list of contract dicts into master_contracts."""
    created = 0
    for raw in contracts:
        data = _normalize(raw, broker)
        if not data["symbol"]:
            continue
        row = MasterContract(**data)
        session.add(row)
        created += 1
    await session.commit()
    return {"imported": created}


async def sync_contracts(
    session: AsyncSession,
    broker: str,
    contracts: Iterable[dict],
) -> dict:
    """Sync contracts for a broker (upsert by symbol/exchange/broker/expiry/strike)."""
    updated = 0
    created = 0
    for raw in contracts:
        data = _normalize(raw, broker)
        if not data["symbol"]:
            continue
        stmt = select(MasterContract).where(
            MasterContract.symbol == data["symbol"],
            MasterContract.exchange == data["exchange"],
            MasterContract.broker == data["broker"],
            MasterContract.expiry == data["expiry"],
            MasterContract.strike == data["strike"],
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            for key, value in data.items():
                setattr(existing, key, value)
            updated += 1
        else:
            session.add(MasterContract(**data))
            created += 1
    await session.commit()
    return {"broker": broker, "created": created, "updated": updated}


async def import_csv(
    session: AsyncSession,
    csv_text: str,
    broker: Optional[str] = None,
) -> dict:
    """Import contracts from CSV text."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = [dict(r) for r in reader]
    return await import_contracts(session, rows, broker=broker)


async def list_contracts(
    session: AsyncSession,
    q: Optional[str] = None,
    exchange: Optional[str] = None,
    broker: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    stmt = select(MasterContract)
    if q:
        stmt = stmt.where(MasterContract.symbol.ilike(f"%{q}%"))
    if exchange:
        stmt = stmt.where(MasterContract.exchange == exchange.upper())
    if broker:
        stmt = stmt.where(MasterContract.broker == broker)
    stmt = stmt.limit(min(limit, 500))
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "exchange": r.exchange,
            "instrument_type": r.instrument_type,
            "underlying": r.underlying,
            "expiry": r.expiry,
            "strike": r.strike,
            "lot_size": r.lot_size,
            "broker": r.broker,
        }
        for r in rows
    ]
