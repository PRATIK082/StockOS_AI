"""Broker plugin routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser
from app.brokers.plugin_loader import list_plugins, load_broker_class, plugin_supports

router = APIRouter(prefix="/brokers", tags=["brokers"])


@router.get("/plugins")
async def list_broker_plugins(user: CurrentUser) -> dict:
    return {"plugins": list_plugins()}


@router.get("/plugins/{name}/supports/{capability}")
async def supports(name: str, capability: str, user: CurrentUser) -> dict:
    try:
        return {"name": name, "capability": capability, "supported": plugin_supports(name, capability)}
    except FileNotFoundError:
        return {"name": name, "capability": capability, "supported": False}
