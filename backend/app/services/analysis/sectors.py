"""Sector & cap-classification analysis over the real symbol universe.

Groups real, live quotes (price, daily change, sector, market cap) by sector
and by size class (small/mid/large/mega cap). No fabricated data: symbols whose
provider returns no quote or no sector are simply excluded / bucketed as
"Unclassified" / "n/a" — honest degradation.

One `get_quote` per symbol (cached 60s in the market service), so repeated page
loads are cheap and the first load is bounded by Yahoo's throughput.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.services.data.service import MarketDataService, market_data
from app.services.data.universe import UNIVERSE, SymbolInfo

logger = get_logger("analysis.sectors")

_CONCURRENCY = 8

# market cap thresholds by market currency
# INR (₹ Cr): SMALL < 10k Cr, MID < 50k Cr, LARGE < 3L Cr, else MEGA
_INR_CAP_BANDS = [(1e11, "SMALL"), (5e11, "MID"), (3e12, "LARGE")]
# USD: SMALL < $2B, MID < $10B, LARGE < $200B, else MEGA
_USD_CAP_BANDS = [(2e9, "SMALL"), (1e10, "MID"), (2e11, "LARGE")]


def cap_class(market_cap: float | None, symbol: str) -> str:
    """Classify a market cap into small/mid/large/mega by market currency."""
    if not isinstance(market_cap, (int, float)) or not market_cap:
        return "n/a"
    ex = symbol.split(":")[0] if ":" in symbol else ""
    bands = _INR_CAP_BANDS if ex in {"NSE", "BSE", "BOM", "NSEFO", "BSEFO"} else _USD_CAP_BANDS
    for threshold, label in bands:
        if market_cap < threshold:
            return label
    return "MEGA"


def _universe_symbols(market: str) -> list[SymbolInfo]:
    return [s for s in UNIVERSE if s.market == market and not s.index]


class SectorAnalysisService:
    """Computes sector and cap breakdowns from real quotes."""

    def __init__(self, market_service: MarketDataService | None = None):
        self.market_service = market_service or market_data

    async def analyze(self, market: str = "india") -> dict:
        symbols = _universe_symbols(market)
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def enrich(sym: SymbolInfo) -> dict | None:
            async with sem:
                try:
                    quote = await self.market_service.get_quote(sym.symbol)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("sector quote failed for %s: %s", sym.symbol, exc)
                    return None
            price = quote.get("price")
            if not isinstance(price, (int, float)):
                return None
            mc = quote.get("market_cap")
            return {
                "symbol": sym.symbol,
                "name": quote.get("name") or sym.name,
                "price": float(price),
                "change_pct": quote.get("day_change_pct"),
                "sector": quote.get("sector") if isinstance(quote.get("sector"), str) else None,
                "industry": quote.get("industry"),
                "market_cap": mc,
                "cap_class": cap_class(mc, sym.symbol),
            }

        enriched = [
            r for r in await asyncio.gather(*(enrich(s) for s in symbols), return_exceptions=True)
            if isinstance(r, dict)
        ]
        enriched.sort(key=lambda r: (r["change_pct"] if isinstance(r["change_pct"], (int, float)) else -999), reverse=True)

        sectors: dict[str, list[dict]] = {}
        for r in enriched:
            sectors.setdefault(r["sector"] or "Unclassified", []).append(r)

        def _avg_change(rows: list[dict]) -> float | None:
            changes = [r["change_pct"] for r in rows if isinstance(r["change_pct"], (int, float))]
            return round(float(sum(changes)) / len(changes), 4) if changes else None

        sector_rows = []
        for name, rows in sectors.items():
            industries: dict[str, list[dict]] = {}
            for r in rows:
                industries.setdefault(r["industry"] or "Other", []).append(r)
            industry_rows = [
                {"name": iname, "count": len(irows), "avg_change_pct": _avg_change(irows), "constituents": irows}
                for iname, irows in sorted(industries.items())
            ]
            sector_rows.append({
                "name": name,
                "count": len(rows),
                "avg_change_pct": _avg_change(rows),
                "top": rows[0] if rows else None,
                "bottom": rows[-1] if rows else None,
                "industries": industry_rows,
                "constituents": rows,
            })
        sector_rows.sort(key=lambda s: (s["avg_change_pct"] if s["avg_change_pct"] is not None else -999), reverse=True)

        caps: dict[str, list[dict]] = {}
        for r in enriched:
            caps.setdefault(r["cap_class"], []).append(r)

        return {
            "market": market,
            "total_symbols": len(symbols),
            "analyzed": len(enriched),
            "sectors": sector_rows,
            "caps": {
                label: rows
                for label in ("MEGA", "LARGE", "MID", "SMALL", "n/a")
                for rows in [caps.get(label, [])]
            },
            "top_gainers": [r for r in enriched if isinstance(r["change_pct"], (int, float)) and r["change_pct"] > 0][:5],
            "top_losers": list(reversed([r for r in enriched if isinstance(r["change_pct"], (int, float)) and r["change_pct"] < 0]))[:5],
        }


sector_analysis_service = SectorAnalysisService()
