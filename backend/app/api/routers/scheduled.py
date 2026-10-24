"""Scheduled research routes: IANA-timezone cron schedules + playbook runs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.services.scheduler.cron import CronError
from app.services.scheduler.runner import run_playbook
from app.services.scheduler.service import scheduled_research_service
from app.services.agents.swarm_presets import list_presets

router = APIRouter(prefix="/scheduled", tags=["scheduled"])

_VALID_PLAYBOOK_TYPES = {"technical_summary", "backtest", "factor_ic", "swarm", "autopilot"}


def _validate_playbook(pb: dict) -> None:
    if not isinstance(pb, dict) or pb.get("type") not in _VALID_PLAYBOOK_TYPES:
        raise HTTPException(status_code=422, detail="playbook.type must be one of " + ", ".join(sorted(_VALID_PLAYBOOK_TYPES)))
    if pb.get("type") != "autopilot" and not (pb.get("symbols") or pb.get("symbol")):
        raise HTTPException(status_code=422, detail="playbook needs symbols or a symbol")


@router.get("/presets")
async def scheduled_presets(current_user=Depends(get_current_user)):
    return {"presets": list_presets()}


@router.get("")
async def list_schedules(current_user=Depends(get_current_user)):
    return await scheduled_research_service.list(current_user.id)


@router.post("")
async def create_schedule(
    body: dict[str, Any],
    current_user=Depends(get_current_user),
):
    name = body.get("name")
    cron_expr = body.get("cron_expr")
    playbook = body.get("playbook")
    timezone = body.get("timezone", "UTC")
    if not name or not cron_expr or not playbook:
        raise HTTPException(status_code=422, detail="name, cron_expr and playbook are required")
    _validate_playbook(playbook)
    try:
        return await scheduled_research_service.create(
            current_user.id, name, playbook, cron_expr, timezone
        )
    except CronError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    body: dict[str, Any],
    current_user=Depends(get_current_user),
):
    if "playbook" in body:
        _validate_playbook(body["playbook"])
    try:
        result = await scheduled_research_service.update(
            current_user.id,
            schedule_id,
            name=body.get("name"),
            playbook=body.get("playbook"),
            cron_expr=body.get("cron_expr"),
            timezone_name=body.get("timezone"),
            enabled=body.get("enabled"),
        )
    except (CronError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return result


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str, current_user=Depends(get_current_user)):
    deleted = await scheduled_research_service.delete(current_user.id, schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="schedule not found")
    return {"deleted": True}


@router.post("/{schedule_id}/run")
async def run_schedule_now(schedule_id: str, current_user=Depends(get_current_user)):
    """Execute the schedule's playbook immediately and record the run."""
    schedule = await scheduled_research_service.get(current_user.id, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    result = await run_playbook(schedule["playbook"], user_id=current_user.id)
    await scheduled_research_service.mark_run(schedule_id, {"status": "error" if "error" in result else "done", "output": result})
    return result


@router.get("/{schedule_id}/runs")
async def schedule_runs(
    schedule_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
):
    schedule = await scheduled_research_service.get(current_user.id, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return await scheduled_research_service.runs(current_user.id, schedule_id, limit)
