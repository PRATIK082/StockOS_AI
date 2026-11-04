"""Python Strategy Host routes (Phase 8).

User-scoped CRUD for strategy scripts, out-of-process run/stop, captured
logs, and encrypted (write-only) env vars. Paper-only in v1; live orders
always go through the approval path when semi-auto is on.

Contract (frontend already built against these — honored exactly):
- write bodies use canonical keys {name, code, schedule_cron, enabled};
- env PUT accepts a FLAT MERGE dict {"KEY": "value"} (None deletes a key);
- env GET returns set-key NAMES ONLY, never values;
- logs returns {logs: [lines], ...};
- run returns a run id + status synchronously (execution is async in worker).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.db.session import get_session
from app.services.strategy_host import runner
from app.services.strategy_host import store

router = APIRouter(prefix="/strategy-host", tags=["strategy-host"])


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = ""
    schedule_cron: str | None = None
    enabled: bool = True


class ScriptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = None
    schedule_cron: str | None = None
    enabled: bool | None = None


class RunRequest(BaseModel):
    timeout_seconds: float | None = None


def _script_payload(
    row_dict: dict[str, Any], user_id: str
) -> dict[str, Any]:
    """Enrich a script dict with latest-run extras (tolerant for the UI)."""
    latest = runner.latest_run_for_script(user_id, str(row_dict.get("id")))
    payload = dict(row_dict)
    if latest is not None:
        payload["last_run_id"] = latest.get("run_id")
        payload["last_run_status"] = latest.get("status")
        payload["last_run_at"] = latest.get("ended_at") or latest.get("started_at")
    else:
        payload["last_run_id"] = None
        payload["last_run_status"] = None
        payload["last_run_at"] = None
    return payload


@router.get("/scripts")
async def list_scripts(
    user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    rows = await store.list_scripts(session, user.id)
    return [_script_payload(store.to_dict(r), user.id) for r in rows]


@router.post("/scripts", status_code=status.HTTP_201_CREATED)
async def create_script(
    body: ScriptCreate, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    row = await store.create_script(
        session,
        user.id,
        name=body.name.strip(),
        code=body.code or "",
        schedule_cron=(body.schedule_cron.strip() if body.schedule_cron and body.schedule_cron.strip() else None),
        enabled=body.enabled,
    )
    return _script_payload(store.to_dict(row), user.id)


@router.get("/scripts/{script_id}")
async def get_script(
    script_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    row = await store.get_script(session, user.id, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy script not found")
    return _script_payload(store.to_dict(row), user.id)


@router.patch("/scripts/{script_id}")
async def patch_script(
    script_id: str,
    body: ScriptUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Any:
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.code is not None:
        fields["code"] = body.code
    if "schedule_cron" in body.model_fields_set:
        raw = body.schedule_cron
        fields["schedule_cron"] = raw.strip() if raw and raw.strip() else None
    if body.enabled is not None:
        fields["enabled"] = body.enabled
    row = await store.update_script(session, user.id, script_id, **fields)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy script not found")
    return _script_payload(store.to_dict(row), user.id)


@router.delete("/scripts/{script_id}")
async def delete_script(
    script_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    ok = await store.delete_script(session, user.id, script_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy script not found")
    return {"id": script_id, "deleted": True}


@router.post("/scripts/{script_id}/run")
async def run_script(
    script_id: str,
    body: RunRequest | None = None,
    user: CurrentUser = None,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = await store.get_script(session, user.id, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy script not found")
    env = await store.get_env_values(session, user.id, script_id) or {}
    try:
        snap = runner.start_run(
            script_id=script_id,
            user_id=user.id,
            code=row.code or "",
            env=env,
            timeout_seconds=(body.timeout_seconds if body else None),
            database_url=get_settings().database_url,
        )
    except runner.AlreadyRunning as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Run already in progress for this script (run_id={exc.run_id})",
        ) from exc
    return {
        "run_id": snap["run_id"],
        "script_id": script_id,
        "status": snap["status"],
        "timeout_seconds": snap.get("timeout_seconds"),
        "started_at": snap.get("started_at"),
    }


@router.post("/scripts/{script_id}/stop")
async def stop_script(
    script_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    row = await store.get_script(session, user.id, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy script not found")
    latest = runner.latest_run_for_script(user.id, script_id)
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No runs for this script")
    outcome = runner.stop_run(latest["run_id"])
    if outcome is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run no longer tracked")
    await runner.reap_run(latest["run_id"])
    return {
        "run_id": latest["run_id"],
        "script_id": script_id,
        "status": outcome.get("status"),
        "stopped": bool(outcome.get("stopped")),
    }


@router.get("/scripts/{script_id}/logs")
async def get_logs(
    script_id: str,
    tail: int = Query(default=200, ge=1, le=2000),
    user: CurrentUser = None,  # type: ignore[assignment]
    session: AsyncSession = Depends(get_session),
) -> Any:
    row = await store.get_script(session, user.id, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy script not found")
    latest = runner.latest_run_for_script(user.id, script_id)
    if latest is None:
        return {"run_id": None, "script_id": script_id, "status": "never_run", "logs": []}
    env = await store.get_env_values(session, user.id, script_id) or {}
    await runner.reap_run(latest["run_id"])  # file fresh intents before reading
    payload = runner.read_logs(latest["run_id"], tail=tail, secrets=list(env.values()))
    if payload is None:
        return {"run_id": latest["run_id"], "script_id": script_id,
                "status": latest.get("status"), "logs": []}
    return payload


@router.get("/scripts/{script_id}/env")
async def get_env(
    script_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> Any:
    keys = await store.get_env_keys(session, user.id, script_id)
    if keys is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy script not found")
    return {"keys": keys}  # NAMES ONLY — values are write-only, never echoed


@router.put("/scripts/{script_id}/env")
async def put_env(
    script_id: str, body: dict[str, Any], user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> Any:
    if not isinstance(body, dict) or not body:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Env body must be a non-empty object")
    try:
        merged = await store.merge_env(session, user.id, script_id, body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if merged is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy script not found")
    keys, updated = merged
    return {"keys": keys, "updated": updated}
