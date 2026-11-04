"""Flow Visual Strategy Builder routes (Phase 7).

CRUD for user-scoped flow graphs, pure validation, dry-run/live execution,
and JSON import/export. Unknown node types are rejected with 422 at the API
boundary; missing market data degrades honestly to nulls + notes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_session
from app.services.flow import store as flow_store
from app.services.flow.executor import run_graph
from app.services.flow.schemas import (
    NODE_TYPES,
    FlowGraph,
    GraphCreate,
    GraphUpdate,
    RunRequest,
)
from app.services.flow.validator import validate

router = APIRouter(prefix="/flow", tags=["flow"])


def _reject_unknown_types(graph: FlowGraph) -> None:
    unknown = sorted({n.type for n in graph.nodes} - set(NODE_TYPES))
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown node type(s): {unknown} (allowed: {sorted(NODE_TYPES)})",
        )


def _payload_to_graph(definition: Any) -> FlowGraph:
    try:
        return FlowGraph.model_validate(definition or {})
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid flow graph: {exc}"
        ) from exc


@router.get("/graphs")
async def list_graphs(
    user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    rows = await flow_store.list_graphs(session, user.id)
    return [flow_store.to_dict(r) for r in rows]


@router.post("/graphs", status_code=status.HTTP_201_CREATED)
async def create_graph(
    body: GraphCreate, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    _reject_unknown_types(body.graph)
    row = await flow_store.create_graph(
        session,
        user.id,
        name=body.name.strip(),
        definition=body.graph.model_dump(by_alias=True, mode="json"),
        schedule_cron=body.schedule_cron,
        enabled=body.enabled,
        paper_only=body.paper_only,
    )
    return flow_store.to_dict(row)


@router.get("/graphs/{graph_id}")
async def get_graph(
    graph_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    row = await flow_store.get_graph(session, user.id, graph_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flow graph not found")
    return flow_store.to_dict(row)


@router.patch("/graphs/{graph_id}")
async def patch_graph(
    graph_id: str,
    body: GraphUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Any:
    if body.graph is not None:
        _reject_unknown_types(body.graph)
    row = await flow_store.update_graph(
        session,
        user.id,
        graph_id,
        name=body.name.strip() if body.name else None,
        definition=body.graph.model_dump(by_alias=True, mode="json") if body.graph else None,
        schedule_cron=body.schedule_cron,
        enabled=body.enabled,
        paper_only=body.paper_only,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flow graph not found")
    return flow_store.to_dict(row)


@router.delete("/graphs/{graph_id}")
async def delete_graph(
    graph_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    ok = await flow_store.delete_graph(session, user.id, graph_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flow graph not found")
    return {"id": graph_id, "deleted": True}


@router.post("/validate")
async def validate_graph(body: dict[str, Any], user: CurrentUser) -> Any:
    payload = body.get("graph", body)
    graph = _payload_to_graph(payload)
    _reject_unknown_types(graph)
    findings = validate(graph)
    return {
        "valid": not findings,
        "findings": [f.model_dump() for f in findings],
    }


@router.post("/run")
async def run_flow(
    body: RunRequest, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    if body.graph_id:
        row = await flow_store.get_graph(session, user.id, body.graph_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Flow graph not found")
        payload = flow_store.to_dict(row)
        graph = _payload_to_graph(payload.get("definition"))
        paper_only = bool(payload.get("paper_only", True))
    elif body.inline_graph is not None:
        graph = body.inline_graph
        paper_only = True
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide graph_id or inline_graph",
        )
    _reject_unknown_types(graph)
    report = await run_graph(graph, body.mode, user.id, paper_only=paper_only)
    return report.model_dump(mode="json")


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_graph(
    body: dict[str, Any], user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    payload = body.get("graph", body)
    definition = payload.get("definition", payload) if isinstance(payload, dict) else payload
    graph = _payload_to_graph(definition)
    _reject_unknown_types(graph)
    name = str((body.get("name") or payload.get("name")) if isinstance(payload, dict) else "" or "Imported flow")
    if not name.strip():
        name = "Imported flow"
    row = await flow_store.create_graph(
        session,
        user.id,
        name=name.strip()[:128],
        definition=graph.model_dump(by_alias=True, mode="json"),
        schedule_cron=(payload.get("schedule_cron") if isinstance(payload, dict) else None),
        enabled=bool((payload.get("enabled", True)) if isinstance(payload, dict) else True),
        paper_only=bool((payload.get("paper_only", True)) if isinstance(payload, dict) else True),
    )
    return flow_store.to_dict(row)


@router.get("/export/{graph_id}")
async def export_graph(
    graph_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    row = await flow_store.get_graph(session, user.id, graph_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flow graph not found")
    payload = flow_store.to_dict(row)
    payload["exported_at"] = datetime.now(timezone.utc).isoformat()
    return payload
