"""Historify market-data warehouse routes (DuckDB)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_session
from app.services.historify import store, jobs

router = APIRouter(prefix="/historify", tags=["historify"])


def _auth(user: CurrentUser):
    return user


# --------------------------------------------------------------------------- status
@router.get("/status")
async def historify_status(user: CurrentUser) -> dict:
    return {"rows": store.count(), "symbols": store.symbols(), "catalog": store.list_catalog()}


@router.get("/stats")
async def historify_stats(user: CurrentUser) -> dict:
    return await historify_status(user)


@router.get("/intervals")
async def historify_intervals(user: CurrentUser) -> dict:
    return {"intervals": ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"]}


# --------------------------------------------------------------------------- ingest
@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_records(body: dict, user: CurrentUser) -> dict:
    records = body.get("records") or []
    if not isinstance(records, list) or not records:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "records must be a non-empty list")
    inserted = store.ingest(records)
    return {"ingested": inserted}


@router.post("/ingest/incremental", status_code=status.HTTP_201_CREATED)
async def ingest_incremental_records(body: dict, user: CurrentUser) -> dict:
    records = body.get("records") or []
    if not isinstance(records, list) or not records:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "records must be a non-empty list")
    result = store.incremental_ingest(records)
    return result


@router.post("/incremental", status_code=status.HTTP_201_CREATED)
async def incremental_alias(body: dict, user: CurrentUser) -> dict:
    return await ingest_incremental_records(body, user)


# --------------------------------------------------------------------------- query
@router.get("/query")
async def query_records(
    symbol: str,
    interval: str = "1d",
    limit: int = 100,
    exchange: str | None = None,
    user: CurrentUser = None,
) -> dict:
    rows = store.query(symbol, interval, limit, exchange=exchange)
    return {"symbol": symbol.upper(), "interval": interval, "rows": rows}


@router.get("/bars")
async def bars_alias(symbol: str, interval: str = "1d", limit: int = 100, exchange: str | None = None, user: CurrentUser = None) -> dict:
    return await query_records(symbol, interval, limit, exchange, user)


@router.get("/gaps")
async def gaps(symbol: str, interval: str = "1d", exchange: str = "NSE", user: CurrentUser = None) -> dict:
    return {"symbol": symbol.upper(), "interval": interval, "gaps": store.find_gaps(symbol, exchange, interval)}


# --------------------------------------------------------------------------- watchlist
@router.get("/watchlist")
async def list_watchlist(user: CurrentUser) -> list[dict]:
    return store.list_watchlist()


@router.post("/watchlist", status_code=status.HTTP_201_CREATED)
async def add_watchlist(body: dict, user: CurrentUser) -> dict:
    symbol = body.get("symbol")
    if not symbol:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "symbol is required")
    exchange = body.get("exchange", "NSE")
    item = store.add_watchlist(symbol, exchange)
    # bulk support
    if body.get("symbols"):
        items = store.bulk_watchlist(body["symbols"], exchange)
        return {"items": items}
    return item


@router.post("/watchlist/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_watchlist(body: dict, user: CurrentUser) -> dict:
    symbols = body.get("symbols") or []
    exchange = body.get("exchange", "NSE")
    return {"items": store.bulk_watchlist(symbols, exchange)}


@router.delete("/watchlist/{symbol}")
async def remove_watchlist(symbol: str, exchange: str | None = None, user: CurrentUser = None) -> dict:
    store.remove_watchlist(symbol, exchange)
    return {"removed": symbol.upper()}


@router.post("/watchlist/remove")
async def remove_watchlist_post(body: dict, user: CurrentUser) -> dict:
    store.remove_watchlist(body.get("symbol", ""), body.get("exchange"))
    return {"removed": (body.get("symbol") or "").upper()}


# --------------------------------------------------------------------------- catalog
@router.get("/catalog")
async def list_catalog(symbol: str | None = None, exchange: str | None = None, interval: str | None = None, user: CurrentUser = None) -> list[dict]:
    return store.list_catalog(symbol, exchange, interval)


@router.get("/catalog/{symbol}")
async def get_catalog(symbol: str, exchange: str | None = None, interval: str | None = None, user: CurrentUser = None) -> list[dict]:
    return store.list_catalog(symbol, exchange, interval)


@router.delete("/catalog/{symbol}")
async def delete_catalog(symbol: str, exchange: str | None = None, interval: str | None = None, user: CurrentUser = None) -> dict:
    deleted = store.delete_dataset(symbol, exchange, interval)
    return {"deleted": deleted, "symbol": symbol.upper()}


@router.delete("/dataset/{symbol}")
async def delete_dataset(symbol: str, exchange: str | None = None, interval: str | None = None, user: CurrentUser = None) -> dict:
    return await delete_catalog(symbol, exchange, interval, user)


# --------------------------------------------------------------------------- jobs
def _create_job_from_body(body: dict) -> str:
    symbols = body.get("symbols") or []
    if body.get("watchlist"):
        symbols = [w["symbol"] for w in store.list_watchlist()]
    if not symbols:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "symbols must be a non-empty list (or watchlist=true)")
    exchange = body.get("exchange", "NSE")
    interval = body.get("interval", "1d")
    period = body.get("period")
    start_date = body.get("start_date") or body.get("start")
    end_date = body.get("end_date") or body.get("end")
    return store.create_job(symbols, exchange, interval, period, start_date, end_date, body)


@router.post("/jobs/download", status_code=status.HTTP_201_CREATED)
async def create_download_job(body: dict, background_tasks: BackgroundTasks, user: CurrentUser) -> dict:
    job_id = _create_job_from_body(body)
    background_tasks.add_task(jobs.run_download_job, job_id)
    job = store.get_job(job_id)
    return job


@router.post("/download", status_code=status.HTTP_201_CREATED)
async def download_alias(body: dict, background_tasks: BackgroundTasks, user: CurrentUser) -> dict:
    return await create_download_job(body, background_tasks, user)


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job_alias(body: dict, background_tasks: BackgroundTasks, user: CurrentUser) -> dict:
    return await create_download_job(body, background_tasks, user)


@router.get("/jobs")
async def list_jobs(limit: int = 50, user: CurrentUser = None) -> list[dict]:
    return store.list_jobs(limit)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: CurrentUser = None) -> dict:
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, user: CurrentUser = None) -> dict:
    store.pause_job(job_id)
    return store.get_job(job_id)


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, user: CurrentUser = None) -> dict:
    store.resume_job(job_id)
    return store.get_job(job_id)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user: CurrentUser = None) -> dict:
    store.cancel_job(job_id)
    return store.get_job(job_id)


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, background_tasks: BackgroundTasks, user: CurrentUser = None) -> dict:
    store.retry_job(job_id)
    background_tasks.add_task(jobs.run_download_job, job_id)
    return store.get_job(job_id)


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, user: CurrentUser = None) -> dict:
    # cancel + leave row; basic delete
    store.cancel_job(job_id)
    return {"deleted": job_id}


# --------------------------------------------------------------------------- import/export
@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_data(body: dict | None = None, user: CurrentUser = None) -> dict:
    body = body or {}
    records = body.get("records")
    if records:
        mode = body.get("mode", "incremental")
        return store.import_records(records, mode)
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "records must be provided (or use file upload)")


@router.post("/import/csv", status_code=status.HTTP_201_CREATED)
async def import_csv(file: UploadFile = File(...), exchange: str = "NSE", interval: str = "1d", user: CurrentUser = None) -> dict:
    suffix = Path(file.filename or "data.csv").suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        records = store.read_csv_records(tmp_path)
        # normalize
        for r in records:
            r.setdefault("exchange", exchange)
            r.setdefault("interval", interval)
            r.setdefault("symbol", r.get("symbol") or r.get("Symbol"))
        res = store.import_records(records, "incremental")
        return res
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/import/parquet", status_code=status.HTTP_201_CREATED)
async def import_parquet(file: UploadFile = File(...), exchange: str = "NSE", interval: str = "1d", user: CurrentUser = None) -> dict:
    suffix = Path(file.filename or "data.parquet").suffix or ".parquet"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        records = store.read_parquet_records(tmp_path)
        for r in records:
            r.setdefault("exchange", exchange)
            r.setdefault("interval", interval)
        res = store.import_records(records, "incremental")
        return res
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.get("/export")
async def export_data(symbol: str, interval: str = "1d", exchange: str | None = None, format: str = "csv", limit: int = 5000, user: CurrentUser = None):
    rows = store.export_records(symbol, exchange, interval, limit)
    if format.lower() == "json":
        return {"symbol": symbol.upper(), "interval": interval, "rows": rows}
    if format.lower() == "parquet":
        with tempfile.NamedTemporaryFile(delete=False, suffix=".parquet") as tmp:
            path = store.write_parquet(tmp.name, rows)
        return FileResponse(path, media_type="application/octet-stream", filename=f"{symbol}_{interval}.parquet")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", newline="") as tmp:
        path = store.write_csv(tmp.name, rows)
    return FileResponse(path, media_type="text/csv", filename=f"{symbol}_{interval}.csv")


@router.get("/export/csv")
async def export_csv(symbol: str, interval: str = "1d", exchange: str | None = None, limit: int = 5000, user: CurrentUser = None):
    return await export_data(symbol, interval, exchange, "csv", limit, user)


@router.get("/export/parquet")
async def export_parquet(symbol: str, interval: str = "1d", exchange: str | None = None, limit: int = 5000, user: CurrentUser = None):
    return await export_data(symbol, interval, exchange, "parquet", limit, user)


@router.get("/export/json")
async def export_json(symbol: str, interval: str = "1d", exchange: str | None = None, limit: int = 5000, user: CurrentUser = None):
    return await export_data(symbol, interval, exchange, "json", limit, user)


# --------------------------------------------------------------------------- FNO metadata
@router.get("/fno/underlyings")
async def fno_underlyings(user: CurrentUser = None) -> list[str]:
    return store.fno_underlyings()


@router.get("/fno/expiries")
async def fno_expiries(underlying: str, user: CurrentUser = None) -> list[str]:
    return store.fno_expiries(underlying)


@router.get("/fno/contracts")
async def fno_contracts(underlying: str, expiry: str | None = None, instrument_type: str | None = None, user: CurrentUser = None) -> list[dict]:
    return store.fno_contracts(underlying, expiry, instrument_type)


@router.get("/fno/futures")
async def fno_futures(underlying: str, expiry: str | None = None, user: CurrentUser = None) -> list[dict]:
    return store.fno_contracts(underlying, expiry, "FUTURE")


@router.get("/fno/options")
async def fno_options(underlying: str, expiry: str | None = None, user: CurrentUser = None) -> list[dict]:
    return store.fno_contracts(underlying, expiry, "CE") + store.fno_contracts(underlying, expiry, "PE")


@router.get("/fno/chain")
async def fno_chain(underlying: str, expiry: str | None = None, user: CurrentUser = None) -> list[dict]:
    return store.fno_contracts(underlying, expiry)


@router.get("/symbol-metadata")
async def list_symbol_metadata(underlying: str | None = None, instrument_type: str | None = None, expiry: str | None = None, exchange: str | None = None, user: CurrentUser = None) -> list[dict]:
    return store.list_symbol_metadata(underlying, instrument_type, expiry, exchange)


@router.get("/metadata")
async def metadata_alias(underlying: str | None = None, instrument_type: str | None = None, expiry: str | None = None, exchange: str | None = None, user: CurrentUser = None) -> list[dict]:
    return await list_symbol_metadata(underlying, instrument_type, expiry, exchange, user)


@router.post("/symbol-metadata", status_code=status.HTTP_201_CREATED)
async def upsert_symbol_metadata(body: dict, user: CurrentUser) -> dict:
    return store.upsert_symbol_metadata(
        symbol=body.get("symbol", ""),
        exchange=body.get("exchange", "NSE"),
        instrument_type=body.get("instrument_type", body.get("type", "EQUITY")),
        underlying=body.get("underlying"),
        expiry=body.get("expiry"),
        strike=body.get("strike"),
        lot_size=body.get("lot_size", 1),
        tick_size=body.get("tick_size"),
        broker=body.get("broker"),
    )


@router.post("/metadata", status_code=status.HTTP_201_CREATED)
async def metadata_create_alias(body: dict, user: CurrentUser) -> dict:
    return await upsert_symbol_metadata(body, user)
