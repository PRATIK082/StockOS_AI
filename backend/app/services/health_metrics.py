"""Process + database health snapshot (Phase 9a).

Only reports measurable values; anything unavailable is returned as null
rather than fabricated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psutil

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("health-metrics")


def get_health() -> dict[str, Any]:
    proc = psutil.Process()
    try:
        with proc.oneshot():
            rss_mb: float | None = round(proc.memory_info().rss / (1024 * 1024), 2)
            threads: int | None = proc.num_threads()
            try:
                fds: int | None = proc.num_fds()
            except AttributeError:
                fds = proc.num_handles()  # Windows has handles, not fds
            cpu_percent: float | None = proc.cpu_percent(interval=None)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        logger.warning(f"process stats unavailable: {exc}")
        rss_mb, threads, fds, cpu_percent = None, None, None, None
    return {
        "app": settings.app_name,
        "environment": settings.environment,
        "process": {
            "rss_mb": rss_mb,
            "threads": threads,
            "fds": fds,
            "cpu_percent": cpu_percent,
        },
        "database": _db_info(),
    }


def _db_info() -> dict[str, Any]:
    url = settings.database_url
    if not url.startswith("sqlite"):
        return {"kind": "remote", "size_mb": None}
    try:
        path = Path(url.split("///")[-1])
        size = path.stat().st_size if path.exists() else None
    except OSError:
        size = None
    return {
        "kind": "sqlite",
        "size_mb": round(size / (1024 * 1024), 2) if size is not None else None,
    }
