"""In-memory IP / username brute-force protection."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.core.config import settings

# Configurable threshold/window (defaults; can be overridden via settings/env).
FAILURE_THRESHOLD = getattr(settings, "ip_ban_threshold", 5)
WINDOW_MINUTES = getattr(settings, "ip_ban_window_minutes", 15)

_failed: dict[str, list[datetime]] = defaultdict(list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _threshold() -> int:
    try:
        from app.core.config import settings
        return int(getattr(settings, "ip_ban_threshold", FAILURE_THRESHOLD))
    except Exception:
        return FAILURE_THRESHOLD


def _window_minutes() -> int:
    try:
        from app.core.config import settings
        return int(getattr(settings, "ip_ban_window_minutes", WINDOW_MINUTES))
    except Exception:
        return WINDOW_MINUTES


def _window() -> timedelta:
    return timedelta(minutes=_window_minutes())


def _prune(key: str) -> None:
    cutoff = _now() - _window()
    _failed[key] = [t for t in _failed.get(key, []) if t >= cutoff]


def record_failure(key: str) -> None:
    _failed[key].append(_now())
    _prune(key)


def failure_count(key: str) -> int:
    _prune(key)
    return len(_failed.get(key, []))


def is_blocked(key: str) -> bool:
    return failure_count(key) >= _threshold()


def clear_failures(*keys: str) -> None:
    for k in keys:
        _failed.pop(k, None)


def reset_all() -> None:
    _failed.clear()


def keys_for(ip: str, identifier: str) -> list[str]:
    ident = (identifier or "").strip().lower()
    out = []
    if ident:
        out.append(f"user:{ident}")
    out.append(f"ipuser:{ip}|{ident}")
    return out