"""Request metrics middleware (Phase 9a).

Records per-route latency / status into the ``request_metrics`` table with a
7-day retention prune. A metrics failure never breaks the request it measures.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger("metrics")

METRICS_RETENTION_DAYS = 7
_PRUNE_EVERY_N_REQUESTS = 100
_request_counter = 0


class MetricsMiddleware(BaseHTTPMiddleware):
    """Time each request and persist route/method/status/duration."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        try:
            await _record(request, response.status_code, elapsed_ms)
        except Exception as exc:  # never break a request because of metrics
            logger.warning(f"metrics record failed: {exc}")
        return response


async def _record(request: Request, status_code: int, duration_ms: float) -> None:
    from app.db.models.monitoring import RequestMetric
    from app.db.session import SessionFactory

    route = request.scope.get("route")
    template = getattr(route, "path", None) or request.url.path
    async with SessionFactory() as session:
        session.add(
            RequestMetric(
                route=str(template)[:512],
                method=request.method.upper()[:8],
                status_code=int(status_code),
                duration_ms=float(duration_ms),
                created_at=datetime.utcnow(),
            )
        )
        await session.commit()
        global _request_counter
        _request_counter += 1
        if _request_counter % _PRUNE_EVERY_N_REQUESTS == 0:
            pruned = await prune_old_metrics(session, METRICS_RETENTION_DAYS)
            logger.info(f"metrics prune removed {pruned} rows")


async def prune_old_metrics(session: AsyncSession, days: int = METRICS_RETENTION_DAYS) -> int:
    """Delete metric rows older than ``days``. Returns rows removed."""
    from app.db.models.monitoring import RequestMetric

    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await session.execute(delete(RequestMetric).where(RequestMetric.created_at < cutoff))
    await session.commit()
    return int(result.rowcount or 0)
