"""Background download job runner for Historify."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from app.services.historify import store
from app.services.data.service import market_data


def _filter_candles(candles, start_date, end_date):
    out = []
    for c in candles or []:
        ts = str(c.get("ts"))
        if start_date and ts < str(start_date):
            continue
        if end_date and ts > str(end_date):
            continue
        out.append(c)
    return out


def _to_records(symbol, exchange, interval, candles, provider):
    records = []
    for c in candles or []:
        records.append(
            {
                "symbol": symbol.upper(),
                "exchange": exchange.upper(),
                "interval": interval,
                "ts": c.get("ts"),
                "open": c.get("open"),
                "high": c.get("high"),
                "low": c.get("low"),
                "close": c.get("close"),
                "volume": c.get("volume", 0),
                "provider": provider,
            }
        )
    return records


async def run_download_job(job_id: str) -> None:
    job = store.get_job(job_id)
    if not job:
        return
    if job["status"] in ("canceled",):
        return
    store.update_job(job_id, status="running", error=None)
    items = store.get_job_items(job_id)
    completed = 0
    failed = 0
    total = len(items)
    try:
        for item in items:
            # refresh job state
            current = store.get_job(job_id)
            if not current:
                return
            if current["status"] == "canceled":
                # mark remaining queued items canceled
                for it in store.get_job_items(job_id):
                    if it["status"] in ("queued", "running"):
                        store.update_job_item(it["id"], status="canceled")
                store.update_job(job_id, status="canceled")
                return
            while current["status"] == "paused":
                await asyncio.sleep(0.5)
                current = store.get_job(job_id)
                if not current or current["status"] == "canceled":
                    store.update_job(job_id, status="canceled")
                    return

            store.update_job_item(item["id"], status="running")
            try:
                period = job.get("period") or "5y"
                history = await market_data.get_history(item["symbol"], interval=item["interval"], period=period)
                provider = history.get("provider")
                candles = _filter_candles(history.get("candles", []), job.get("start_date"), job.get("end_date"))
                records = _to_records(item["symbol"], item["exchange"], item["interval"], candles, provider)
                if records:
                    res = store.incremental_ingest(records)
                    inserted = res.get("inserted", 0)
                else:
                    inserted = 0
                store.update_job_item(item["id"], status="completed", rows=inserted)
                completed += 1
                store.refresh_catalog(item["symbol"], item["exchange"], item["interval"])
            except Exception as exc:  # noqa: BLE001
                store.update_job_item(item["id"], status="failed", error=str(exc))
                failed += 1
            store.update_job(job_id, completed=completed, failed=failed, total=total)
        final_status = "completed"
        store.update_job(job_id, status=final_status, completed=completed, failed=failed, total=total)
    except Exception as exc:  # noqa: BLE001
        store.update_job(job_id, status="failed", error=str(exc))


async def run_all_queued() -> None:
    for job in store.list_jobs(100):
        if job["status"] == "queued":
            await run_download_job(job["id"])
