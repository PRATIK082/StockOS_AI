"""AgentMemory model: persistent, per-user key/value memory for agents.

``key`` is a namespaced identifier (e.g. ``insight:NSE:RELIANCE:2024-01-01``),
``value`` holds the JSON payload, ``kind`` groups memories (insight/fact/note),
``scope`` optionally ties the memory to a symbol or surface. Storing memories
is how agents stop re-deriving the same conclusion every request.
"""

from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import CoreModel


class AgentMemory(CoreModel):
    __tablename__ = "agent_memories"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_memory_user_key"),)

    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="note", nullable=False)
    scope: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
