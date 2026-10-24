"""Dependency-free MCP server over stdio (JSON-RPC 2.0).

Speaks the Model Context Protocol transport that Claude Desktop / Cursor etc.
use to launch local servers: newline-delimited JSON requests on stdin, JSON
responses on stdout. Implements ``initialize``, ``notifications/initialized``,
``tools/list`` and ``tools/call``; every tool is real (see ``tools.TOOLS``).

Run with ``uv run python -m app.services.mcp`` and point your MCP client at
the command."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from app.services.mcp.tools import TOOL_LIST, TOOLS

SERVER_INFO = {"name": "stockos", "version": "0.1.0"}
PROTOCOL_VERSION = "2025-03-26"


def _rpc_error(code: int, message: str, request_id: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def handle_message(raw: str) -> dict | None:
    """Dispatch one JSON-RPC message; returns the response (None for
    notifications). Raises ValueError on malformed JSON."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return _rpc_error(-32700, "Parse error", None)
    method = msg.get("method")
    request_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOL_LIST}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = TOOLS.get(name)
        if tool is None:
            return _rpc_error(-32602, f"unknown tool '{name}'", request_id)
        try:
            result = await tool[2](arguments)
        except Exception as exc:  # a tool failure must not kill the server
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"isError": True, "content": [{"type": "text", "text": f"error: {exc}"}]},
            }
        text = result if isinstance(result, str) else json.dumps(result, default=str)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": text}]},
        }
    return _rpc_error(-32601, f"method not found: {method}", request_id)


async def _serve_stdio() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = await handle_message(line)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def main() -> None:
    asyncio.run(_serve_stdio())


if __name__ == "__main__":
    main()
