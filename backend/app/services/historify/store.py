"""DuckDB-backed OHLCV warehouse (Historify)."""

from __future__ import annotations

import os
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
    return conn


def init_schema() -> None:
    conn = _connect()
    conn.close()


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
        return count
    finally:
        conn.close()


def query(symbol: str, interval: str = "1d", limit: int = 100) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT symbol, exchange, interval, ts, open, high, low, close, volume, provider
            FROM ohlcv
            WHERE symbol = ? AND interval = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            [symbol.upper(), interval, min(max(limit, 1), 5000)],
        ).fetchall()
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
