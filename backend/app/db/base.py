"""Declarative base and shared column types."""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings


def gen_uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    """Common base for all ORM models."""


class CoreModel(Base):
    """Base with id, created_at, updated_at for auditable rows."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=gen_uuid)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )