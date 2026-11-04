"""CRUD helpers for FlowGraph rows (Phase 7). All helpers are user-scoped."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.flow_graph import FlowGraph as FlowGraphRow


def to_dict(row: FlowGraphRow) -> dict[str, Any]:
    try:
        definition = json.loads(row.definition or "{}")
    except (ValueError, TypeError):
        definition = {}
    created = row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at
    updated = row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at
    return {
        "id": row.id,
        "name": row.name,
        "definition": definition,
        "schedule_cron": row.schedule_cron,
        "enabled": bool(row.enabled),
        "paper_only": bool(row.paper_only),
        "created_at": created,
        "updated_at": updated,
    }


async def create_graph(
    session: AsyncSession,
    user_id: str,
    *,
    name: str,
    definition: dict[str, Any],
    schedule_cron: str | None = None,
    enabled: bool = True,
    paper_only: bool = True,
) -> FlowGraphRow:
    row = FlowGraphRow(
        user_id=user_id,
        name=name,
        definition=json.dumps(definition),
        schedule_cron=schedule_cron,
        enabled=enabled,
        paper_only=paper_only,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_graphs(session: AsyncSession, user_id: str) -> list[FlowGraphRow]:
    result = await session.execute(
        select(FlowGraphRow)
        .where(FlowGraphRow.user_id == user_id)
        .order_by(FlowGraphRow.created_at.desc())
    )
    return list(result.scalars().all())


async def get_graph(session: AsyncSession, user_id: str, graph_id: str) -> FlowGraphRow | None:
    return await session.scalar(
        select(FlowGraphRow).where(
            FlowGraphRow.id == graph_id, FlowGraphRow.user_id == user_id
        )
    )


async def update_graph(
    session: AsyncSession,
    user_id: str,
    graph_id: str,
    **fields: Any,
) -> FlowGraphRow | None:
    row = await get_graph(session, user_id, graph_id)
    if row is None:
        return None
    if "name" in fields and fields["name"] is not None:
        row.name = fields["name"]
    if "definition" in fields and fields["definition"] is not None:
        row.definition = json.dumps(fields["definition"])
    if "schedule_cron" in fields:
        row.schedule_cron = fields["schedule_cron"]
    if "enabled" in fields and fields["enabled"] is not None:
        row.enabled = bool(fields["enabled"])
    if "paper_only" in fields and fields["paper_only"] is not None:
        row.paper_only = bool(fields["paper_only"])
    await session.commit()
    await session.refresh(row)
    return row


async def delete_graph(session: AsyncSession, user_id: str, graph_id: str) -> bool:
    row = await get_graph(session, user_id, graph_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
