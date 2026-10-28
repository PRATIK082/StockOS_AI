"""Rate limiting helpers (slowapi)."""

from __future__ import annotations

from app.core.config import settings
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_default_per_minute}/minute"],
)
