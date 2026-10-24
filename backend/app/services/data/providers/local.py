"""Local CSV/Parquet data provider.

Loads OHLCV from a configured directory (``LOCAL_DATA_ROOT``), so users can
bring their own data. Symbols use the form ``LOCAL:filename`` (or bare
``filename`` when only the local source is requested). Column names are matched
case-insensitively (``date/time``, ``open``, ``high``, ``low``, ``close``,
``volume``). A ``local:`` symbol never silently falls back to a network source.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings
from app.services.data.providers.base import MarketDataProvider, parse_symbol

_SUPPORTED_EXTS = {".csv", ".parquet", ".pq"}


def _resolve_path(symbol: str) -> Path | None:
    ex, tick = parse_symbol(symbol)
    if ex and ex not in {"LOCAL"}:
        return None
    root = Path(settings.data_local_root)
    if not root.exists():
        return None
    candidates = [root / f"{tick}.csv", root / f"{tick}.parquet", root / f"{tick}.pq"]
    if tick and not Path(tick).suffix:
        # allow "LOCAL:myfile.csv"
        candidates.append(root / tick)
    for c in candidates:
        if c.exists() and c.suffix.lower() in _SUPPORTED_EXTS:
            return c
    return None


def _load_df(symbol: str) -> pd.DataFrame | None:
    path = _resolve_path(symbol)
    if path is None:
        return None
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_parquet(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    rename = {}
    for c in df.columns:
        if c in {"date", "datetime", "time", "timestamp", "ts", "day"}:
            rename[c] = "ts"
        elif c in {"open", "o"}:
            rename[c] = "open"
        elif c in {"high", "h"}:
            rename[c] = "high"
        elif c in {"low", "l"}:
            rename[c] = "low"
        elif c in {"close", "c", "adj close", "adjclose"}:
            rename[c] = "close"
        elif c in {"volume", "vol", "v"}:
            rename[c] = "volume"
    df = df.rename(columns=rename)
    needed = {"ts", "open", "high", "low", "close"}
    if not needed.issubset(df.columns):
        return None
    df = df[["ts", "open", "high", "low", "close", "volume"]].copy() if "volume" in df.columns else df[list(needed)]
    if "volume" not in df.columns:
        df["volume"] = 0
    return df


def _to_history(symbol: str, df: pd.DataFrame, interval: str) -> dict[str, Any]:
    candles: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        candles.append(
            {
                "ts": row["ts"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(float(row.get("volume") or 0)),
            }
        )
    return {"symbol": symbol, "interval": interval, "candles": candles}


class LocalProvider(MarketDataProvider):
    name = "local"
    display_name = "Local files (CSV/Parquet)"

    async def get_quote(self, symbol: str) -> dict:
        df = await asyncio.to_thread(_load_df, symbol)
        if df is None or df.empty:
            raise FileNotFoundError(f"No local OHLCV file for '{symbol}' under {settings.data_local_root}")
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        price = float(last["close"])
        prev_close = float(prev["close"])
        change_pct = (price / prev_close - 1) * 100 if prev_close else None
        return {
            "symbol": symbol,
            "name": symbol,
            "price": price,
            "previous_close": prev_close,
            "open": float(last.get("open")),
            "high": float(last.get("high")),
            "low": float(last.get("low")),
            "volume": int(float(last.get("volume") or 0)),
            "currency": None,
            "day_change_pct": change_pct,
            "provider": "local",
        }

    async def get_history(self, symbol: str, *, interval: str = "1d", period: str = "1y") -> dict:
        df = await asyncio.to_thread(_load_df, symbol)
        if df is None or df.empty:
            raise FileNotFoundError(f"No local OHLCV file for '{symbol}' under {settings.data_local_root}")
        return _to_history(symbol, df, interval)

    async def get_fundamentals(self, symbol: str) -> dict:
        return {"symbol": symbol, "provider": "local", "note": "Fundamentals not available for local data."}

    async def health(self) -> bool:
        return Path(settings.data_local_root).exists()
