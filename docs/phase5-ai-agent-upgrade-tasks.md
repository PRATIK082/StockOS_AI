# Phase 5 — AI Agent Upgrade: Concrete Implementation Tasks

Branch: `feature/openalgo-adaptation` (local only)

## Already available in StockOS
- [x] Multi-agent research/analysis services (`app/services/agents/*`).
- [x] MCP server exposing 62 StockOS tools (`app/services/mcp/*`).
- [x] Action Center approval queue for orders (`app/services/action_center.py`, router).
- [x] Provider/model registry endpoint (`/api/trading/providers`).

## Completed in Phase 5
- [x] MCP client service to consume external MCP servers
      (`app/services/mcp/client.py`: `MCPClient`, `MCPClientService`,
      stdio + SSE transports) with routes under `/api/mcp/clients`.
- [x] Agent -> chart markup integration
      (`app/services/agents/chart_markup.py`: `ChartMarkupService`) exposed at
      `/api/analysis/chart-markup` and `/api/chart-markup`.
- [x] Model registry data endpoints (`/api/llm/registry`, `/api/trading/model-registry`).
- [x] Tests: `test_mcp_client.py`, `test_chart_markup.py`, `test_model_registry.py`.

## Still pending
- [ ] Optional: migrate agent runtime to Agno + LiteLLM (existing agents keep working).
- [ ] Frontend surfaces for MCP clients, chart markup, and model registry.
- [ ] Voice / attachments / web-search / skills in the agent runtime.
