"""Routes for consuming external MCP servers."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.services.mcp.client import mcp_client_service

router = APIRouter(prefix="/mcp/clients", tags=["mcp-client"])


class StdioConnectRequest(BaseModel):
    name: str
    command: list[str] | str
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: Optional[str] = None
    timeout: float = 30.0


class SseConnectRequest(BaseModel):
    name: str
    url: str
    timeout: float = 30.0


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] | None = None


@router.get("")
async def list_clients(user: CurrentUser) -> dict:
    return {"clients": mcp_client_service.list_servers()}


@router.post("/stdio", status_code=status.HTTP_201_CREATED)
async def connect_stdio(body: StdioConnectRequest, user: CurrentUser) -> dict:
    try:
        client = await mcp_client_service.connect_stdio(
            body.name, body.command, args=body.args, env=body.env, cwd=body.cwd, timeout=body.timeout
        )
        tools = await client.list_tools()
        return {"name": body.name, "transport": "stdio", "tools": [t.get("name") for t in tools if isinstance(t, dict)]}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to connect stdio MCP server: {exc}") from exc


@router.post("/sse", status_code=status.HTTP_201_CREATED)
async def connect_sse(body: SseConnectRequest, user: CurrentUser) -> dict:
    try:
        client = await mcp_client_service.connect_sse(body.name, body.url, timeout=body.timeout)
        tools = await client.list_tools()
        return {"name": body.name, "transport": "sse", "tools": [t.get("name") for t in tools if isinstance(t, dict)]}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to connect SSE MCP server: {exc}") from exc


@router.get("/{name}/tools")
async def list_tools(name: str, user: CurrentUser) -> dict:
    client = mcp_client_service.get(name)
    if client is None:
        raise HTTPException(status_code=404, detail="MCP client not found")
    tools = await client.list_tools()
    return {"name": name, "tools": tools}


@router.post("/{name}/call/{tool}")
async def call_tool(name: str, tool: str, body: ToolCallRequest, user: CurrentUser) -> dict:
    client = mcp_client_service.get(name)
    if client is None:
        raise HTTPException(status_code=404, detail="MCP client not found")
    try:
        result = await client.call_tool(tool, body.arguments or {})
        return {"name": name, "tool": tool, "result": result}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Tool call failed: {exc}") from exc


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(name: str, user: CurrentUser) -> None:
    if not await mcp_client_service.disconnect(name):
        raise HTTPException(status_code=404, detail="MCP client not found")
