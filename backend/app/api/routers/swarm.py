"""Swarm router: list DAG presets, fetch one as a DAG, run a preset
deterministically over real data (no LLM)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.services.agents.swarm_presets import build_dag, list_presets
from app.services.scheduler.runner import run_playbook

router = APIRouter(prefix="/swarm", tags=["swarm"])


@router.get("/presets")
async def swarm_presets(current_user=Depends(get_current_user)):
    return {"presets": list_presets(), "count": len(list_presets())}


@router.get("/presets/{preset_id}")
async def swarm_preset_dag(preset_id: str, current_user=Depends(get_current_user)):
    dag = build_dag(preset_id)
    if "error" in dag:
        raise HTTPException(status_code=404, detail=dag["error"])
    return dag


@router.post("/run")
async def swarm_run(
    body: dict[str, Any],
    current_user=Depends(get_current_user),
):
    preset = body.get("preset")
    symbols = body.get("symbols") or []
    if not preset:
        raise HTTPException(status_code=422, detail="preset required")
    if not symbols:
        raise HTTPException(status_code=422, detail="symbols required")
    result = await run_playbook({"type": "swarm", "preset": preset, "symbols": symbols})
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result
