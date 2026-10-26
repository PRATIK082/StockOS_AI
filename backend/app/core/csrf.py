"""CSRF protection helpers and middleware (double-submit cookie)."""

from __future__ import annotations

import secrets
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CSRF_COOKIE_NAMES = ("csrf_token", "csrftoken", "XSRF-TOKEN")
CSRF_HEADER_NAMES = ("x-csrf-token", "x-xsrf-token", "x-csrftoken")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _csrf_cookie_value(request: Request) -> str | None:
    for name in CSRF_COOKIE_NAMES:
        val = request.cookies.get(name)
        if val:
            return val
    return None


def _csrf_header_value(request: Request) -> str | None:
    for name in CSRF_HEADER_NAMES:
        val = request.headers.get(name)
        if val:
            return val
    return None


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection.

    Bearer-token clients (Authorization header present) are exempt, as are
    requests without a CSRF cookie. Only state-changing requests carrying a
    CSRF cookie must also present a matching header token.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method.upper()
        if method not in STATE_CHANGING:
            return await call_next(request)
        # Bearer clients are not cookie-authenticated -> exempt.
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return await call_next(request)
        # Preflight / health / docs exemption.
        path = request.url.path or ""
        if path in ("/healthz",) or path.startswith("/docs") or path.startswith("/openapi"):
            return await call_next(request)

        cookie_val = _csrf_cookie_value(request)
        if not cookie_val:
            # No CSRF cookie -> nothing to validate (backward compatible).
            return await call_next(request)

        header_val = _csrf_header_value(request)
        if not header_val or header_val != cookie_val:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
        return await call_next(request)
