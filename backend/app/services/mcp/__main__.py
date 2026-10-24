"""MCP server entry point: ``uv run python -m app.services.mcp``."""

from app.services.mcp.server import main

if __name__ == "__main__":
    main()
