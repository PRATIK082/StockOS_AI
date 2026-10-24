"""Agent memory routes: per-user persistent key/value memories used by agents
to persist insights and by the swarm/research surfaces to store notes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services.memory.store import memory_store

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("")
async def set_memory(
    body: dict[str, Any],
    current_user: dict = Depends(get_current_user),
):
    key = body.get("key")
    if not key:
        raise HTTPException(status_code=422, detail="key required")
    value = body.get("value", "")
    result = await memory_store.set(
        current_user.id,
        key,
        value,
        kind=str(body.get("kind", "note")),
        scope=str(body.get("scope", "")),
    )
    return result


@router.get("")
async def list_memory(
    kind: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    return await memory_store.list(current_user.id, kind=kind, scope=scope, limit=limit)


@router.delete("/{key}")
async def delete_memory(key: str, current_user: dict = Depends(get_current_user)):
    deleted = await memory_store.delete(current_user.id, key)
    return {"deleted": deleted}
