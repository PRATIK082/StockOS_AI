"""Monitoring routes (Phase 9a): latency percentiles, traffic, health."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.models.monitoring import RequestMetric
from app.db.session import get_session

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def _cutoff(window_hours: int) -> datetime:
    return datetime.utcnow() - timedelta(hours=max(1, window_hours))


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


@router.get("/latency")
async def latency(
    window_hours: int = Query(24, ge=1, le=168),
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Per-route count / avg / p50 / p95 latency over the window."""
    rows = (
        (
            await session.execute(
                select(RequestMetric.route, RequestMetric.duration_ms).where(
                    RequestMetric.created_at >= _cutoff(window_hours)
                )
            )
        )
        .all()
    )
    by_route: dict[str, list[float]] = {}
    for route, ms in rows:
        by_route.setdefault(str(route), []).append(float(ms))
    out = []
    for route in sorted(by_route):
        vals = sorted(by_route[route])
        n = len(vals)
        out.append(
            {
                "route": route,
                "count": n,
                "avg_ms": round(sum(vals) / n, 2),
                "p50_ms": round(_percentile(vals, 50), 2),
                "p95_ms": round(_percentile(vals, 95), 2),
            }
        )
    return {"window_hours": window_hours, "routes": out}


@router.get("/traffic")
async def traffic(
    window_hours: int = Query(24, ge=1, le=168),
    user: CurrentUser = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Per-route request counts + 5xx error counts over the window."""
    rows = (
        await session.execute(
            select(
                RequestMetric.route,
                func.count().label("count"),
                func.sum(case((RequestMetric.status_code >= 500, 1), else_=0)).label("errors"),
            )
            .where(RequestMetric.created_at >= _cutoff(window_hours))
            .group_by(RequestMetric.route)
            .order_by(RequestMetric.route)
        )
    ).all()
    return {
        "window_hours": window_hours,
        "routes": [
            {
                "route": str(route),
                "count": int(count),
                "errors": int(errors or 0),
                "error_rate": round(float(errors or 0) / int(count), 4) if count else 0.0,
            }
            for route, count, errors in rows
        ],
    }


@router.get("/health")
async def health(user: CurrentUser = None) -> Any:
    """Process + database health snapshot (authenticated)."""
    from app.services.health_metrics import get_health

    return get_health()
