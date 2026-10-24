"""Autopilot routes — drive the multi-agent supervisor from the terminal.

Endpoints:
- GET  /autopilot/state            config + mode + last review/run
- POST /autopilot/toggle           enable/disable the autopilot (paper)
- POST /autopilot/config           persist mission tunables (partial patch)
- POST /autopilot/run              run a full mission (or monitor-only)
- GET  /autopilot/runs             mission history
- GET  /autopilot/runs/{id}        one mission with its node trace
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.services.autopilot.engine import autopilot_engine

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


class AutopilotToggle(BaseModel):
    enabled: bool


class AutopilotConfigBody(BaseModel):
    """Optional fields — only the ones provided are patched onto the saved config."""

    enabled: bool | None = None
    market: str | None = None
    scanners: list[str] | None = None
    watchlist: list[str] | None = None
    max_new_entries: int | None = Field(default=None, ge=0, le=10)
    entry_qty: int | None = Field(default=None, ge=1, le=10000)
    take_profit_pct: float | None = Field(default=None, ge=0)
    stop_loss_pct: float | None = Field(default=None, le=0)
    trail_enabled: bool | None = None
    trail_drop_pct: float | None = Field(default=None, ge=0.1)
    option_enabled: bool | None = None
    option_max_plays: int | None = Field(default=None, ge=0, le=10)
    option_lots: int | None = Field(default=None, ge=1, le=100)
    use_llm: bool | None = None


@router.get("/state")
async def autopilot_state(user: CurrentUser) -> dict:
    return await autopilot_engine.state(user.id)


@router.post("/toggle")
async def autopilot_toggle(body: AutopilotToggle, user: CurrentUser) -> dict:
    return await autopilot_engine.toggle(user.id, body.enabled)


@router.post("/config")
async def autopilot_set_config(body: AutopilotConfigBody, user: CurrentUser) -> dict:
    payload: dict[str, Any] = {k: v for k, v in body.model_dump().items() if v is not None}
    return await autopilot_engine.save_config(user.id, payload)


@router.post("/run")
async def autopilot_run(user: CurrentUser, monitor_only: bool = False) -> dict:
    return await autopilot_engine.run(user.id, monitor_only=monitor_only)


@router.get("/runs")
async def autopilot_runs(user: CurrentUser, limit: int = 20) -> dict:
    runs = await autopilot_engine.list_runs(user.id, limit=limit)
    return {"runs": runs}


@router.get("/runs/{run_id}")
async def autopilot_run_detail(run_id: str, user: CurrentUser) -> dict:
    run = await autopilot_engine.get_run(user.id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Autopilot run not found")
    return run