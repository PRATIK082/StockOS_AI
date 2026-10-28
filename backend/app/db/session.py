"""Async SQLAlchemy engine / session factories.

Uses SQLite (aiosqlite) for local development and PostgreSQL (asyncpg) when a
Postgres DSN is provided — no code changes required between the two.
"""

from __future__ import annotations

import importlib

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.inspection import inspect as sa_inspect

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import Base

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


async def init_db() -> None:
    """Create missing tables and add missing columns for local upgrades."""

    # Import all models so Base.metadata is fully populated.
    importlib.import_module("app.db.models")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(conn) -> None:
    inspector = sa_inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            col_type = col.type.compile(dialect=conn.dialect)
            conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'))
            # Backfill simple scalar defaults for pre-existing rows.
            default = col.default
            default_value = getattr(default, "arg", None) if default is not None else None
            if default_value is not None and not callable(default_value):
                conn.execute(
                    text(
                        f'UPDATE "{table.name}" SET "{col.name}" = :value '
                        f'WHERE "{col.name}" IS NULL'
                    ),
                    {"value": default_value},
                )


async def get_session() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    async with SessionFactory() as session:
        yield session
