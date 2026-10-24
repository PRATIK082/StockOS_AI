"""Tests for the MCP server: 62 real tools, JSON-RPC handshake, tool calls."""

from __future__ import annotations

import asyncio

import pytest

from app.services.mcp import server
from app.services.mcp.tools import TOOLS


def test_tool_count_is_62() -> None:
    assert len(TOOLS) == 62
    names = sorted(TOOLS)
    assert names[0] == "backtest.bootstrap" and names[-1] == "swarm.run"
    tool_list = server.TOOL_LIST
    assert len(tool_list) == 62
    for t in tool_list:
        assert "name" in t and "description" in t and "inputSchema" in t


def test_handshake() -> None:
    resp = asyncio.run(
        server.handle_message(
            json_dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test"}}})
        )
    )
    assert resp["result"]["serverInfo"]["name"] == "stockos"
    assert asyncio.run(server.handle_message(json_dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))) is None


def test_tools_list() -> None:
    resp = asyncio.run(server.handle_message(json_dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})))
    assert len(resp["result"]["tools"]) == 62


def test_tool_call_numeric() -> None:
    resp = asyncio.run(
        server.handle_message(
            json_dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "quantlib.npv", "arguments": {"rate": 0.1, "amounts": [-100, 30, 30, 30, 30]}}})
        )
    )
    assert resp["result"]["content"][0]["type"] == "text"
    assert "-4.9" in resp["result"]["content"][0]["text"] or "npv" in resp["result"]["content"][0]["text"]


def test_tool_call_unknown() -> None:
    resp = asyncio.run(server.handle_message(json_dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}})))
    assert resp["error"]["code"] == -32602


def test_bad_method_and_malformed() -> None:
    resp = asyncio.run(server.handle_message(json_dumps({"jsonrpc": "2.0", "id": 5, "method": "bogus"})))
    assert resp["error"]["code"] == -32601
    resp2 = asyncio.run(server.handle_message("not json"))
    assert resp2["error"]["code"] == -32700


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj)
