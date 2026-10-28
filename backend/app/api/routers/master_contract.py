"""Master contract routes (broker symbol metadata)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.models import MasterContract
from app.db.session import get_session
from app.services.master_contract import import_contracts, sync_contracts, import_csv

router = APIRouter(prefix="/master-contract", tags=["master-contract"])


@router.get("")
async def list_contracts(
    q: Optional[str] = None,
    exchange: Optional[str] = None,
    limit: int = 50,
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    stmt = select(MasterContract)
    if q:
        stmt = stmt.where(MasterContract.symbol.ilike(f"%{q}%"))
    if exchange:
        stmt = stmt.where(MasterContract.exchange == exchange.upper())
    stmt = stmt.limit(min(limit, 200))
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


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_contract(
    body: dict,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = MasterContract(
        symbol=str(body.get("symbol", "")).upper(),
        exchange=str(body.get("exchange", "NSE")).upper(),
        instrument_type=str(body.get("instrument_type", "EQUITY")).upper(),
        underlying=body.get("underlying"),
        expiry=body.get("expiry"),
        strike=body.get("strike"),
        lot_size=int(body.get("lot_size", 1) or 1),
        broker=body.get("broker"),
    )
    if not row.symbol:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "symbol is required")
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"id": row.id, "symbol": row.symbol, "exchange": row.exchange}


@router.post("/sync", status_code=status.HTTP_200_OK)
async def sync_master_contracts(
    body: dict,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Any:
    broker = str(body.get("broker") or body.get("name") or "").strip().lower()
    contracts = body.get("contracts") or body.get("data") or []
    if not broker:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "broker is required")
    if not isinstance(contracts, list):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "contracts must be a list")
    result = await sync_contracts(session, broker, contracts)
    return result


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_master_contracts(
    body: dict,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Any:
    broker = body.get("broker")
    if "csv" in body and isinstance(body.get("csv"), str):
        result = await import_csv(session, body["csv"], broker=broker)
        return result
    contracts = body.get("contracts") or body.get("data") or []
    if not isinstance(contracts, list):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "contracts must be a list")
    result = await import_contracts(session, contracts, broker=broker)
    return result
