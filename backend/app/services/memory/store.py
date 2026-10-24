"""MemoryStore: async per-user key/value agent memory over ``agent_memories``.

Agents can ``set`` a fact/insight once and ``get`` it on later runs instead of
re-deriving it, and the swarm/research surfaces can persist short notes. Values
are JSON strings; ``kind``/``scope`` make them filterable without denormalizing
the value payload.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select

from app.db.models.memory import AgentMemory
from app.db.session import SessionFactory


class MemoryStore:
    """Stateless service; every call opens its own short session."""

    async def set(
        self,
        user_id: str,
        key: str,
        value: Any,
        *,
        kind: str = "note",
        scope: str = "",
    ) -> dict:
        payload = value if isinstance(value, str) else json.dumps(value)
        async with SessionFactory() as session:
            existing = (
                await session.execute(
                    select(AgentMemory).where(
                        AgentMemory.user_id == user_id, AgentMemory.key == key
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                row = AgentMemory(user_id=user_id, key=key, kind=kind, scope=scope, value=payload)
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return {"key": key, "kind": kind, "scope": scope, "value": value, "created": True}
            existing.value = payload
            existing.kind = kind
            existing.scope = scope
            await session.commit()
            return {"key": key, "kind": kind, "scope": scope, "value": value, "created": False}

    async def get(self, user_id: str, key: str) -> dict | None:
        async with SessionFactory() as session:
            row = (
                await session.execute(
                    select(AgentMemory).where(
                        AgentMemory.user_id == user_id, AgentMemory.key == key
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return self._row_dict(row)

    async def list(
        self,
        user_id: str,
        *,
        kind: str | None = None,
        scope: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        async with SessionFactory() as session:
            stmt = select(AgentMemory).where(AgentMemory.user_id == user_id).order_by(AgentMemory.updated_at.desc())
            if kind:
                stmt = stmt.where(AgentMemory.kind == kind)
            if scope:
                stmt = stmt.where(AgentMemory.scope == scope)
            rows = (await session.execute(stmt.limit(limit))).scalars().all()
        return [self._row_dict(r) for r in rows]

    async def delete(self, user_id: str, key: str) -> bool:
        async with SessionFactory() as session:
            result = await session.execute(
                delete(AgentMemory).where(
                    AgentMemory.user_id == user_id, AgentMemory.key == key
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def remember(self, user_id: str, note: str, *, scope: str = "") -> dict:
        """Convenience for free-form agent notes (auto-keyed by timestamp)."""
        import hashlib

        key = f"note:{hashlib.sha1(note.encode("utf-8")).hexdigest()[:12]}"
        return await self.set(user_id, key, {"note": note, "text": note}, kind="note", scope=scope)

    @staticmethod
    def _row_dict(row: AgentMemory) -> dict:
        value: Any = row.value
        try:
            value = json.loads(row.value)
        except (ValueError, TypeError):
            pass
        return {
            "key": row.key,
            "kind": row.kind,
            "scope": row.scope,
            "value": value,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


memory_store = MemoryStore()
