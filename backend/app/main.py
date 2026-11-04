"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api.routers import api_router
from app.core.config import settings
from app.core.logging import get_logger
from app.core.middleware import SecurityHeadersMiddleware
from app.core.metrics import MetricsMiddleware
from app.core.rate_limit import limiter
from app.core.csrf import CSRFMiddleware, generate_csrf_token

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    logger.info(f"Starting {settings.app_name} in {settings.environment} mode")

    # Ensure local database schema is present and upgraded.
    from app.db.session import init_db
    await init_db()

    # Trading Desk scheduler (interval loop over watchlists).
    scheduler: TradingScheduler | None = None
    if settings.ta_scheduler_enabled:
        from app.services.tradingagents.scheduler import get_scheduler
        scheduler = get_scheduler()
        await scheduler.start()

    # Telegram notifications bot (read-only v1; silent no-op when unconfigured).
    from app.services.telegram.bot import start_bot, stop_bot
    await start_bot()

    # Startup
    yield

    # Shutdown
    await stop_bot()
    if scheduler is not None:
        await scheduler.stop()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Build the FastAPI app instance with middleware and routes."""
    app = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    
    import os
    _cors_raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000")
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    # Private-LAN origins (phone/tablet on the same Wi-Fi hitting http://<lan-ip>:3000).
    # Overridable via CORS_ALLOWED_ORIGIN_REGEX; empty string disables the regex.
    _cors_regex = os.getenv(
        "CORS_ALLOWED_ORIGIN_REGEX",
        r"http://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+)(:\d+)?",
    ) or None
    _allow_credentials = "*" not in _cors_origins
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_origin_regex=_cors_regex,
        allow_credentials=_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Rate limiting + security headers
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(MetricsMiddleware)
    
    # Health check endpoint (+ conventional /health alias)
    @app.get("/healthz", tags=["system"])
    @app.get("/health", tags=["system"], include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok", "app": settings.app_name, "environment": settings.environment}

    # CSRF token aliases (root-level)
    @app.get("/api/csrf")
    @app.get("/api/csrf-token")
    @app.get("/api/csrf_token")
    async def csrf_token_root(response: Response) -> dict:
        token = generate_csrf_token()
        for name in ("csrf_token", "csrftoken", "XSRF-TOKEN"):
            response.set_cookie(name, token, httponly=False, samesite="lax", path="/")
        return {"csrf_token": token, "csrftoken": token, "token": token, "xsrf_token": token}
    
    # Include API routers
    app.include_router(api_router, prefix=settings.api_prefix)
    
    return app


# Create the app instance
app = create_app()