"""Research & chat routes that drive the agent orchestrator."""

from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas import ChatRequest, ResearchRequest
from app.services.agents.orchestrator import orchestrator
from app.services.llm.gateway import gateway
from app.services.vibe.engine import vibe_chat_engine

router = APIRouter(tags=["ai"])


@router.post("/research")
async def research(body: ResearchRequest) -> dict:
    try:
        return await orchestrator.run(
            f"Research {body.symbol}", symbol=body.symbol, intent="research", provider=body.provider
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Research failed: {exc}") from exc


@router.post("/chat")
async def chat(body: ChatRequest) -> dict:
    try:
        return await orchestrator.run(
            body.message, intent="chat", provider=body.provider
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Chat failed: {exc}") from exc


@router.post("/chat/vibe")
async def chat_vibe(body: ChatRequest) -> StreamingResponse:
    """Vibe Trading Chat: stream real StockOS analysis as a series of SSE events.

    Each ``data`` frame is a JSON object:
    - ``{"type": "plan", "plan": [{"key", "label"}...]}`` — the pipeline rail,
    - ``{"type": "stage", "status", "key", "data"}`` — one real-data stage
      (quote, technical, options, prediction),
    - ``{"type": "answer", "data": {"answer", "confidence", "symbol", "sources"}}``
      — the final LLM (or deterministic) verdict.
    """

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in vibe_chat_engine.stream(body.message, provider=body.provider):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        except Exception as exc:  # noqa: BLE001
            yield (
                "data: "
                + json.dumps({"type": "error", "data": {"detail": f"Vibe chat failed: {exc}"}}, ensure_ascii=False)
                + "\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/llm/providers")
async def llm_providers() -> dict:
    from app.services.llm.gateway import SUPPORTED_PROVIDERS

    return {"providers": sorted(SUPPORTED_PROVIDERS)}


@router.get("/llm/models")
async def llm_models(provider: str | None = None) -> dict:
    try:
        return {"models": await gateway.list_models(provider)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to list models: {exc}") from exc


@router.get("/llm/registry")
async def llm_registry() -> dict:
    """Model registry UI data: providers with their available models."""
    from app.services.llm.gateway import SUPPORTED_PROVIDERS

    out = []
    for pid in sorted(SUPPORTED_PROVIDERS):
        try:
            models = await gateway.list_models(pid)
        except Exception:  # noqa: BLE001
            models = []
        out.append({"provider": pid, "models": models})
    return {"default_provider": __import__("app.core.config", fromlist=["settings"]).settings.llm_default_provider, "providers": out}


@router.get("/models/registry")
async def models_registry_alias() -> dict:
    return await llm_registry()
