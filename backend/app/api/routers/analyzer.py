"""Analyzer mode routes (sandbox / paper-live simulation)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.services.analyzer import AnalyzerService


class AnalyzerToggleRequest(BaseModel):
    enabled: Optional[bool] = None
    analyzer_mode: Optional[bool] = None
    mode: Optional[str] = None


class AnalyzerConfigRequest(BaseModel):
    analyzer_mode: Optional[bool] = None
    analyzer_sandbox_capital: Optional[float] = None
    analyzer_margin_percent: Optional[float] = None
    analyzer_square_off_time: Optional[str] = None
    analyzer_session_reset_time: Optional[str] = None


def _apply_toggle(body: AnalyzerToggleRequest) -> bool:
    if body.enabled is not None:
        enabled = body.enabled
    elif body.analyzer_mode is not None:
        enabled = body.analyzer_mode
    elif body.mode is not None:
        enabled = body.mode.lower() in ("analyzer", "paper", "sandbox", "true", "1", "on")
    else:
        enabled = None
    return AnalyzerService.toggle(enabled)


def _status() -> dict:
    return AnalyzerService.status()


# Primary router
router = APIRouter(prefix="/v1/analyzer", tags=["analyzer"])


@router.get("")
@router.get("/")
async def get_analyzer(user: CurrentUser = None) -> Any:
    return _status()


@router.post("/toggle")
async def toggle_analyzer(body: AnalyzerToggleRequest, user: CurrentUser = None) -> Any:
    enabled = _apply_toggle(body)
    return {"analyzer_mode": enabled, **AnalyzerService.status()}


@router.post("/enable")
async def enable_analyzer(user: CurrentUser = None) -> Any:
    AnalyzerService.enable()
    return AnalyzerService.status()


@router.post("/disable")
async def disable_analyzer(user: CurrentUser = None) -> Any:
    AnalyzerService.disable()
    return AnalyzerService.status()


@router.get("/config")
async def get_analyzer_config(user: CurrentUser = None) -> Any:
    return AnalyzerService.status()


@router.patch("/config")
async def patch_analyzer_config(body: AnalyzerConfigRequest, user: CurrentUser = None) -> Any:
    s = get_settings()
    if body.analyzer_mode is not None:
        s.analyzer_mode = body.analyzer_mode
    if body.analyzer_sandbox_capital is not None:
        s.analyzer_sandbox_capital = body.analyzer_sandbox_capital
    if body.analyzer_margin_percent is not None:
        s.analyzer_margin_percent = body.analyzer_margin_percent
    if body.analyzer_square_off_time is not None:
        s.analyzer_square_off_time = body.analyzer_square_off_time
    if body.analyzer_session_reset_time is not None:
        s.analyzer_session_reset_time = body.analyzer_session_reset_time
    return AnalyzerService.status()


# Compatibility router (no /v1)
compat_router = APIRouter(prefix="/analyzer", tags=["analyzer"])


@compat_router.get("")
@compat_router.get("/")
async def get_analyzer_compat(user: CurrentUser = None) -> Any:
    return _status()


@compat_router.post("/toggle")
async def toggle_analyzer_compat(body: AnalyzerToggleRequest, user: CurrentUser = None) -> Any:
    enabled = _apply_toggle(body)
    return {"analyzer_mode": enabled, **AnalyzerService.status()}


@compat_router.post("/enable")
async def enable_analyzer_compat(user: CurrentUser = None) -> Any:
    AnalyzerService.enable()
    return AnalyzerService.status()


@compat_router.post("/disable")
async def disable_analyzer_compat(user: CurrentUser = None) -> Any:
    AnalyzerService.disable()
    return AnalyzerService.status()