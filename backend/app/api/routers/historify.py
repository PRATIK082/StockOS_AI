"""Historify market-data warehouse routes (DuckDB)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_session
from app.services.historify.store import count, ingest, query, symbols

router = APIRouter(prefix="/historify", tags=["historify"])


@router.get("/status")
async def historify_status(user: CurrentUser) -> dict:
    return {"rows": count(), "symbols": symbols()}


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_records(body: dict, user: CurrentUser) -> dict:
    records = body.get("records") or []
    if not isinstance(records, list) or not records:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "records must be a non-empty list")
    inserted = ingest(records)
    return {"ingested": inserted}


@router.get("/query")
async def query_records(
    symbol: str,
    interval: str = "1d",
    limit: int = 100,
    user: CurrentUser = None,
) -> dict:
    rows = query(symbol, interval, limit)
    return {"symbol": symbol.upper(), "interval": interval, "rows": rows}
