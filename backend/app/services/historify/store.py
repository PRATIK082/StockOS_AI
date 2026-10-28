"""DuckDB-backed OHLCV warehouse (Historify)."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb

from app.core.config import settings


def _db_path() -> Path:
    url = settings.database_url
    if url.startswith("sqlite"):
        try:
            data_dir = Path(url.split("///")[-1]).parent
        except Exception:
            data_dir = Path(".")
    else:
        data_dir = Path(".")
    data_dir.mkdir(parents=True, exist_ok=True)
    env = os.getenv("STOCKOS_HISTORIFY_DB")
    if env:
        return Path(env)
    return data_dir / "historify.duckdb"


def _connect() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(_db_path()))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol VARCHAR NOT NULL,
            exchange VARCHAR NOT NULL,
            interval VARCHAR NOT NULL,
            ts TIMESTAMP NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            provider VARCHAR,
            PRIMARY KEY (symbol, exchange, interval, ts)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol VARCHAR NOT NULL,
            exchange VARCHAR NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, exchange)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_catalog (
            symbol VARCHAR NOT NULL,
            exchange VARCHAR NOT NULL,
            interval VARCHAR NOT NULL,
            first_ts TIMESTAMP,
            last_ts TIMESTAMP,
            rows BIGINT DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, exchange, interval)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS download_jobs (
            id VARCHAR PRIMARY KEY,
            status VARCHAR NOT NULL DEFAULT 'queued',
            exchange VARCHAR NOT NULL DEFAULT 'NSE',
            interval VARCHAR NOT NULL DEFAULT '1d',
            period VARCHAR,
            start_date VARCHAR,
            end_date VARCHAR,
            total INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            error VARCHAR,
            config VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_items (
            id VARCHAR PRIMARY KEY,
            job_id VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            exchange VARCHAR NOT NULL,
            interval VARCHAR NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'queued',
            rows INTEGER DEFAULT 0,
            error VARCHAR,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS symbol_metadata (
            symbol VARCHAR NOT NULL,
            exchange VARCHAR NOT NULL,
            instrument_type VARCHAR NOT NULL DEFAULT 'EQUITY',
            underlying VARCHAR,
            expiry VARCHAR,
            strike DOUBLE,
            lot_size INTEGER DEFAULT 1,
            tick_size DOUBLE,
            broker VARCHAR,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (symbol, exchange)
        )
        """
    )
    return conn


def init_schema() -> None:
    conn = _connect()
    conn.close()


def _now() -> str:
    return datetime.utcnow().isoformat()


def _rows_to_dicts(rows, cols):
    return [dict(zip(cols, row)) for row in rows]


# --------------------------------------------------------------------------- OHLCV
def ingest(records: Iterable[dict[str, Any]]) -> int:
    """Insert OHLCV records (upsert by primary key). Returns count inserted/updated."""
    conn = _connect()
    count = 0
    try:
        for r in records:
            conn.execute(
                """
                INSERT INTO ohlcv (symbol, exchange, interval, ts, open, high, low, close, volume, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol, exchange, interval, ts) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume, provider=excluded.provider
                """,
                [
                    str(r.get("symbol", "")).upper(),
                    str(r.get("exchange", "NSE")).upper(),
                    str(r.get("interval", "1d")),
                    r.get("ts"),
                    float(r.get("open", 0) or 0),
                    float(r.get("high", 0) or 0),
                    float(r.get("low", 0) or 0),
                    float(r.get("close", 0) or 0),
                    int(r.get("volume", 0) or 0),
                    r.get("provider"),
                ],
            )
            count += 1
            _upsert_catalog_conn(conn, str(r.get("symbol", "")).upper(), str(r.get("exchange", "NSE")).upper(), str(r.get("interval", "1d")))
        return count
    finally:
        conn.close()


def incremental_ingest(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Append only new bars (skip existing primary keys). Returns counts."""
    conn = _connect()
    inserted = 0
    skipped = 0
    total = 0
    try:
        for r in records:
            total += 1
            symbol = str(r.get("symbol", "")).upper()
            exchange = str(r.get("exchange", "NSE")).upper()
            interval = str(r.get("interval", "1d"))
            ts = r.get("ts")
            exists = conn.execute(
                "SELECT COUNT(*) FROM ohlcv WHERE symbol=? AND exchange=? AND interval=? AND ts=?",
                [symbol, exchange, interval, ts],
            ).fetchone()[0]
            if exists:
                skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO ohlcv (symbol, exchange, interval, ts, open, high, low, close, volume, provider)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    symbol,
                    exchange,
                    interval,
                    ts,
                    float(r.get("open", 0) or 0),
                    float(r.get("high", 0) or 0),
                    float(r.get("low", 0) or 0),
                    float(r.get("close", 0) or 0),
                    int(r.get("volume", 0) or 0),
                    r.get("provider"),
                ],
            )
            inserted += 1
            _upsert_catalog_conn(conn, symbol, exchange, interval)
        return {"inserted": inserted, "skipped": skipped, "total": total}
    finally:
        conn.close()


def query(symbol: str, interval: str = "1d", limit: int = 100, exchange: str | None = None) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        sql = """
            SELECT symbol, exchange, interval, ts, open, high, low, close, volume, provider
            FROM ohlcv
            WHERE symbol = ? AND interval = ?
        """
        params: list[Any] = [symbol.upper(), interval]
        if exchange:
            sql += " AND exchange = ?"
            params.append(exchange.upper())
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(min(max(limit, 1), 5000))
        rows = conn.execute(sql, params).fetchall()
        cols = ["symbol", "exchange", "interval", "ts", "open", "high", "low", "close", "volume", "provider"]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def count() -> int:
    conn = _connect()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0])
    finally:
        conn.close()


def symbols() -> list[str]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def delete_dataset(symbol: str, exchange: str | None = None, interval: str | None = None) -> int:
    conn = _connect()
    try:
        sql = "DELETE FROM ohlcv WHERE symbol = ?"
        params: list[Any] = [symbol.upper()]
        if exchange:
            sql += " AND exchange = ?"
            params.append(exchange.upper())
        if interval:
            sql += " AND interval = ?"
            params.append(interval)
        conn.execute(sql, params)
        deleted = 0
        # duckdb doesn't easily return rowcount; approximate via catalog? keep 0
        # Update catalog
        if interval:
            conn.execute(
                "DELETE FROM data_catalog WHERE symbol=? AND exchange=? AND interval=?",
                [symbol.upper(), (exchange or "NSE").upper(), interval],
            )
        else:
            conn.execute(
                "DELETE FROM data_catalog WHERE symbol=? " + ("AND exchange=?" if exchange else ""),
                [symbol.upper()] + ([exchange.upper()] if exchange else []),
            )
        return deleted
    finally:
        conn.close()


def find_gaps(symbol: str, exchange: str = "NSE", interval: str = "1d", start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    rows = query(symbol, interval, 5000, exchange=exchange)
    rows = sorted(rows, key=lambda r: r["ts"])
    gaps: list[dict[str, Any]] = []
    # simple: report adjacent timestamp jumps; for daily, >2 days
    import datetime as _dt

    def parse(ts):
        try:
            return _dt.datetime.fromisoformat(str(ts).replace("Z", ""))
        except Exception:
            return None

    prev = None
    for r in rows:
        cur = parse(r["ts"])
        if prev is not None and cur is not None:
            delta = (cur - prev).days if interval.endswith("d") or interval in ("1d",) else None
            if delta is not None and delta > 1:
                gaps.append({"from": str(prev.date()), "to": str(cur.date()), "gap_days": delta})
        prev = cur
    return gaps


# --------------------------------------------------------------------------- Catalog helpers
def _upsert_catalog_conn(conn, symbol, exchange, interval):
    try:
        agg = conn.execute(
            """
            SELECT MIN(ts), MAX(ts), COUNT(*) FROM ohlcv
            WHERE symbol=? AND exchange=? AND interval=?
            """,
            [symbol, exchange, interval],
        ).fetchone()
        first_ts, last_ts, cnt = agg
        conn.execute(
            """
            INSERT INTO data_catalog (symbol, exchange, interval, first_ts, last_ts, rows, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, exchange, interval) DO UPDATE SET
                first_ts=excluded.first_ts, last_ts=excluded.last_ts, rows=excluded.rows, updated_at=excluded.updated_at
            """,
            [symbol, exchange, interval, first_ts, last_ts, int(cnt or 0), _now()],
        )
    except Exception:
        pass


def refresh_catalog(symbol: str | None = None, exchange: str | None = None, interval: str | None = None) -> None:
    conn = _connect()
    try:
        q = "SELECT DISTINCT symbol, exchange, interval FROM ohlcv"
        clauses = []
        params = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if exchange:
            clauses.append("exchange = ?")
            params.append(exchange.upper())
        if interval:
            clauses.append("interval = ?")
            params.append(interval)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        rows = conn.execute(q, params).fetchall()
        for s, e, iv in rows:
            _upsert_catalog_conn(conn, s, e, iv)
    finally:
        conn.close()


def list_catalog(symbol: str | None = None, exchange: str | None = None, interval: str | None = None) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        sql = "SELECT symbol, exchange, interval, first_ts, last_ts, rows, updated_at FROM data_catalog WHERE 1=1"
        params: list[Any] = []
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol.upper())
        if exchange:
            sql += " AND exchange = ?"
            params.append(exchange.upper())
        if interval:
            sql += " AND interval = ?"
            params.append(interval)
        sql += " ORDER BY symbol, interval"
        rows = conn.execute(sql, params).fetchall()
        cols = ["symbol", "exchange", "interval", "first_ts", "last_ts", "rows", "updated_at"]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- Watchlist
def list_watchlist() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT symbol, exchange, created_at FROM watchlist ORDER BY symbol").fetchall()
        return [{"symbol": r[0], "exchange": r[1], "created_at": str(r[2]) if r[2] is not None else None} for r in rows]
    finally:
        conn.close()


def add_watchlist(symbol: str, exchange: str = "NSE") -> dict[str, Any]:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO watchlist (symbol, exchange) VALUES (?, ?) ON CONFLICT (symbol, exchange) DO NOTHING",
            [symbol.upper(), exchange.upper()],
        )
        return {"symbol": symbol.upper(), "exchange": exchange.upper()}
    finally:
        conn.close()


def remove_watchlist(symbol: str, exchange: str | None = None) -> None:
    conn = _connect()
    try:
        if exchange:
            conn.execute("DELETE FROM watchlist WHERE symbol=? AND exchange=?", [symbol.upper(), exchange.upper()])
        else:
            conn.execute("DELETE FROM watchlist WHERE symbol=?", [symbol.upper()])
    finally:
        conn.close()


def bulk_watchlist(symbols: list[str], exchange: str = "NSE") -> list[dict[str, Any]]:
    out = []
    for s in symbols:
        out.append(add_watchlist(s, exchange))
    return out


# --------------------------------------------------------------------------- Jobs
def create_job(symbols: list[str], exchange: str = "NSE", interval: str = "1d", period: str | None = None,
               start_date: str | None = None, end_date: str | None = None, config: dict | None = None) -> str:
    import uuid
    job_id = uuid.uuid4().hex
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO download_jobs (id, status, exchange, interval, period, start_date, end_date, total, config, created_at, updated_at)
            VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [job_id, exchange.upper(), interval, period, start_date, end_date, len(symbols), json.dumps(config or {}), _now(), _now()],
        )
    finally:
        conn.close()
    create_job_items(job_id, symbols, exchange, interval)
    return job_id


def create_job_items(job_id: str, symbols: list[str], exchange: str = "NSE", interval: str = "1d") -> None:
    import uuid
    conn = _connect()
    try:
        for s in symbols:
            conn.execute(
                "INSERT INTO job_items (id, job_id, symbol, exchange, interval, status, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                [uuid.uuid4().hex, job_id, s.upper(), exchange.upper(), interval, _now()],
            )
    finally:
        conn.close()


def get_job(job_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, status, exchange, interval, period, start_date, end_date, total, completed, failed, error, config, created_at, updated_at FROM download_jobs WHERE id=?",
            [job_id],
        ).fetchone()
        if not row:
            return None
        cols = ["id", "status", "exchange", "interval", "period", "start_date", "end_date", "total", "completed", "failed", "error", "config", "created_at", "updated_at"]
        job = dict(zip(cols, row))
        try:
            job["config"] = json.loads(job["config"]) if job["config"] else {}
        except Exception:
            pass
        job["items"] = get_job_items(job_id)
        return job
    finally:
        conn.close()


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, status, exchange, interval, period, start_date, end_date, total, completed, failed, error, created_at, updated_at FROM download_jobs ORDER BY created_at DESC LIMIT ?",
            [min(max(limit, 1), 500)],
        ).fetchall()
        cols = ["id", "status", "exchange", "interval", "period", "start_date", "end_date", "total", "completed", "failed", "error", "created_at", "updated_at"]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    conn = _connect()
    try:
        sets = []
        params = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            params.append(v)
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(job_id)
        conn.execute(f"UPDATE download_jobs SET {', '.join(sets)} WHERE id = ?", params)
    finally:
        conn.close()


def get_job_items(job_id: str) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, job_id, symbol, exchange, interval, status, rows, error, updated_at FROM job_items WHERE job_id=? ORDER BY symbol",
            [job_id],
        ).fetchall()
        cols = ["id", "job_id", "symbol", "exchange", "interval", "status", "rows", "error", "updated_at"]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def update_job_item(item_id: str, **fields) -> None:
    if not fields:
        return
    conn = _connect()
    try:
        sets = []
        params = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            params.append(v)
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(item_id)
        conn.execute(f"UPDATE job_items SET {', '.join(sets)} WHERE id = ?", params)
    finally:
        conn.close()


def pause_job(job_id: str) -> None:
    update_job(job_id, status="paused")


def resume_job(job_id: str) -> None:
    update_job(job_id, status="queued")


def cancel_job(job_id: str) -> None:
    update_job(job_id, status="canceled")


def retry_job(job_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE job_items SET status='queued', rows=0, error=NULL, updated_at=? WHERE job_id=?", [_now(), job_id])
    finally:
        conn.close()
    update_job(job_id, status="queued", completed=0, failed=0, error=None)


# --------------------------------------------------------------------------- Symbol metadata / FNO
def upsert_symbol_metadata(symbol: str, exchange: str = "NSE", instrument_type: str = "EQUITY",
                           underlying: str | None = None, expiry: str | None = None,
                           strike: float | None = None, lot_size: int = 1,
                           tick_size: float | None = None, broker: str | None = None) -> dict[str, Any]:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO symbol_metadata (symbol, exchange, instrument_type, underlying, expiry, strike, lot_size, tick_size, broker, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, exchange) DO UPDATE SET
                instrument_type=excluded.instrument_type, underlying=excluded.underlying,
                expiry=excluded.expiry, strike=excluded.strike, lot_size=excluded.lot_size,
                tick_size=excluded.tick_size, broker=excluded.broker, updated_at=excluded.updated_at
            """,
            [symbol.upper(), exchange.upper(), instrument_type.upper(), underlying, expiry, strike, int(lot_size or 1), tick_size, broker, _now()],
        )
        return {"symbol": symbol.upper(), "exchange": exchange.upper(), "instrument_type": instrument_type.upper()}
    finally:
        conn.close()


def list_symbol_metadata(underlying: str | None = None, instrument_type: str | None = None,
                         expiry: str | None = None, exchange: str | None = None) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        sql = "SELECT symbol, exchange, instrument_type, underlying, expiry, strike, lot_size, tick_size, broker, updated_at FROM symbol_metadata WHERE 1=1"
        params: list[Any] = []
        if underlying:
            sql += " AND underlying = ?"
            params.append(underlying.upper())
        if instrument_type:
            sql += " AND instrument_type = ?"
            params.append(instrument_type.upper())
        if expiry:
            sql += " AND expiry = ?"
            params.append(expiry)
        if exchange:
            sql += " AND exchange = ?"
            params.append(exchange.upper())
        sql += " ORDER BY symbol"
        rows = conn.execute(sql, params).fetchall()
        cols = ["symbol", "exchange", "instrument_type", "underlying", "expiry", "strike", "lot_size", "tick_size", "broker", "updated_at"]
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def fno_underlyings() -> list[str]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT underlying FROM symbol_metadata WHERE underlying IS NOT NULL ORDER BY underlying"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def fno_expiries(underlying: str) -> list[str]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT expiry FROM symbol_metadata WHERE underlying=? AND expiry IS NOT NULL ORDER BY expiry",
            [underlying.upper()],
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def fno_contracts(underlying: str, expiry: str | None = None, instrument_type: str | None = None) -> list[dict[str, Any]]:
    return list_symbol_metadata(underlying=underlying, expiry=expiry, instrument_type=instrument_type)


# --------------------------------------------------------------------------- Import/Export helpers
def export_records(symbol: str, exchange: str | None = None, interval: str = "1d", limit: int = 5000) -> list[dict[str, Any]]:
    return query(symbol, interval, limit, exchange=exchange)


def import_records(records: Iterable[dict[str, Any]], mode: str = "incremental") -> dict[str, int]:
    recs = list(records)
    if mode == "replace":
        # upsert all
        n = ingest(recs)
        return {"inserted": n, "skipped": 0, "total": len(recs)}
    return incremental_ingest(recs)


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> str:
    path = Path(path)
    if not rows:
        path.write_text("")
        return str(path)
    cols = list(rows[0].keys())
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(path)


def write_parquet(path: str | Path, rows: list[dict[str, Any]]) -> str:
    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_parquet(path, index=False)
    return str(path)


def read_csv_records(path: str | Path) -> list[dict[str, Any]]:
    import pandas as pd
    df = pd.read_csv(path)
    return df.to_dict(orient="records")


def read_parquet_records(path: str | Path) -> list[dict[str, Any]]:
    import pandas as pd
    df = pd.read_parquet(path)
    return df.to_dict(orient="records")
