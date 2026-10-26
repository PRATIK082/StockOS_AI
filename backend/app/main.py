"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api.routers import api_router
from app.core.config import settings
from app.core.logging import get_logger
from app.core.middleware import SecurityHeadersMiddleware
from app.core.rate_limit import limiter

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

    # Startup
    yield

    # Shutdown
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
    _allow_credentials = "*" not in _cors_origins
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Rate limiting + security headers
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SecurityHeadersMiddleware)
    
    # Health check endpoint
    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict:
        return {"status": "ok", "app": settings.app_name, "environment": settings.environment}
    
    # Include API routers
    app.include_router(api_router, prefix=settings.api_prefix)
    
    return app


# Create the app instance
app = create_app()