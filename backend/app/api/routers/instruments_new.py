"""Enhanced instrument discovery with complete stock database."""

from fastapi import APIRouter, Path, Query
from typing import Optional, List
from app.services.data.universe_expanded import (
    search_symbols, 
    get_market_symbols,
    get_indices,
    get_symbol_info,
    get_all_symbols
)

router = APIRouter(prefix="/instruments", tags=["instruments"])

@router.get("/search")
async def search(
    q: str = Query("", max_length=80),
    market: Optional[str] = Query(None, pattern="^(india|us)$"),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Search symbols with enhanced database."""
    results = search_symbols(q, market=market, limit=limit)
    return {
        "results": [
            {
                "symbol": s.symbol,
                "name": s.name,
                "market": s.market,
                "currency": s.currency,
                "exchange": s.exchange,
                "sector": s.sector,
                "index": s.index
            }
            for s in results
        ]
    }

@router.get("/indices")
async def index_list() -> dict:
    """Get all available indices."""
    indices = get_indices()
    return {
        "results": [
            {
                "symbol": idx.symbol,
                "name": idx.name,
                "market": idx.market,
                "currency": idx.currency,
                "exchange": idx.exchange
            }
            for idx in indices
        ]
    }

@router.get("/market/{market}")
async def by_market_route(
    market: str = Path(..., pattern="^(india|us)$"),
    limit: int = Query(50, ge=1, le=200)
) -> dict:
    """Get top symbols for a market."""
    symbols = get_market_symbols(market, limit=limit)
    return {
        "results": [
            {
                "symbol": s.symbol,
                "name": s.name,
                "currency": s.currency,
                "exchange": s.exchange,
                "sector": s.sector,
                "index": s.index
            }
            for s in symbols
        ]
    }

@router.get("/symbol/{symbol}")
async def get_symbol(symbol: str) -> dict:
    """Get detailed info for a symbol."""
    info = get_symbol_info(symbol)
    if info:
        return {
            "found": True,
            "symbol": info.symbol,
            "name": info.name,
            "market": info.market,
            "currency": info.currency,
            "exchange": info.exchange,
            "sector": info.sector,
            "index": info.index
        }
    return {"found": False, "message": "Symbol not found"}

@router.get("/all")
async def get_all(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500)
) -> dict:
    """Get all available symbols with pagination."""
    all_symbols = get_all_symbols()
    
    # Apply pagination
    paginated = all_symbols[offset:offset + limit]
    
    return {
        "total": len(all_symbols),
        "offset": offset,
        "limit": limit,
        "results": [
            {
                "symbol": s.symbol,
                "name": s.name,
                "market": s.market,
                "currency": s.currency,
                "exchange": s.exchange,
                "sector": s.sector,
                "index": s.index
            }
            for s in paginated
        ]
    }

@router.get("/sectors/{market}")
async def get_sectors(market: str = Path(..., pattern="^(india|us)$")) -> dict:
    """Get all sectors for a market."""
    symbols = get_market_symbols(market, limit=1000)
    
    sectors = {}
    for s in symbols:
        if s.sector and not s.index:
            if s.sector not in sectors:
                sectors[s.sector] = []
            sectors[s.sector].append({
                "symbol": s.symbol,
                "name": s.name
            })
    
    return {"sectors": sectors}