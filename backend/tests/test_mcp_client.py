"""Tests for the MCP client (stdio transport against our own MCP server)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix="smtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR) / 'test.db'}"

import pytest  # noqa: E402

from app.services.mcp.client import MCPClient  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_mcp_client_stdio_handshake_and_tools() -> None:
    client = MCPClient.stdio([sys.executable, "-m", "app.services.mcp"], cwd=str(BACKEND))
    await client.connect()
    try:
        assert client.is_connected
        tools = await client.list_tools()
        assert len(tools) == 62
        names = [t["name"] for t in tools if isinstance(t, dict)]
        assert "quantlib.npv" in names
        result = await client.call_tool("quantlib.npv", {"rate": 0.1, "amounts": [-100, 30, 30, 30, 30]})
        # result may be text or parsed number
        text = result if isinstance(result, str) else str(result)
        assert "-4.9" in text or "npv" in text.lower() or isinstance(result, (int, float, dict))
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_client_unknown_tool_raises() -> None:
    client = MCPClient.stdio([sys.executable, "-m", "app.services.mcp"], cwd=str(BACKEND))
    await client.connect()
    try:
        with pytest.raises(Exception):
            await client.call_tool("nope.tool", {})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_client_service_registry() -> None:
    from app.services.mcp.client import MCPClientService

    svc = MCPClientService()
    client = await svc.connect_stdio("local", [sys.executable, "-m", "app.services.mcp"], cwd=str(BACKEND))
    assert svc.get("local") is client
    assert "local" in svc.list_servers()
    tools = await client.list_tools()
    assert len(tools) == 62
    assert await svc.disconnect("local") is True
    assert svc.get("local") is None
    await svc.close_all()
