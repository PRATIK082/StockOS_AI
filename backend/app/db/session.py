"""Async SQLAlchemy engine / session factories.

Uses SQLite (aiosqlite) for local development and PostgreSQL (asyncpg) when a
Postgres DSN is provided — no code changes required between the two.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.db")

# Ensure the SQLite data directory exists (no-op for Postgres).
if settings.database_url.startswith("sqlite"):
    data_dir = Path(settings.database_url.split("///")[-1]).parent
    data_dir.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug and settings.environment == "development",
    pool_pre_ping=True,
)

SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    async with SessionFactory() as session:
        yield session
