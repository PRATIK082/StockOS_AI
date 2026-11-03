# Phase 5 — AI Agent Upgrade: Concrete Implementation Tasks

Branch: `StockAlgo_1`

## Scope for this iteration
Finish the AI agent upgrade (reference-inspired, original code) without breaking the existing
StockOS agents, MCP server, or Action Center approval flow.

## Already available in StockOS
- [x] Multi-agent research/analysis services (`app/services/agents/*`).
- [x] MCP server exposing StockOS tools (`app/services/mcp/*`).
- [x] Action Center approval queue for orders (`app/services/action_center.py`, router).
- [x] Provider/model registry endpoint (`/api/trading/providers`).

## Completed
- [x] MCP client service to consume external MCP servers (`app/services/mcp/client.py`:
      `MCPClient`, `MCPClientService`, stdio + SSE transports) with routes under `/api/mcp/clients`.
- [x] Agent -> chart markup integration (`app/services/agents/chart_markup.py`:
      `ChartMarkupService`) exposed at `/api/analysis/chart-markup` and `/api/chart-markup`.
- [x] Model registry data endpoints (`/api/llm/registry`, `/api/trading/model-registry`).
- [x] Tests: `test_mcp_client.py`, `test_chart_markup.py`, `test_model_registry.py`.
- [x] Frontend surfaces for MCP clients, chart markup, and model registry
      (`frontend/app/ai-tools/page.tsx`).
- [x] P5-b: agent-tool order approval. New choke point `app/services/agents/tools.py`
      (`list_tools`, `run_tool`, `preview_order` read-only, `place_order` approval-gated:
      `REQUIRE_APPROVAL` files a pending `ActionCenterItem`, no broker contact; PAPER
      mirrors `order_submit` incl. risk check). Autopilot `execute_agent` queues approvals
      the same way and returns a `pending` list (fills stay empty, no direct fill).
      Tests: `tests/test_agent_tools_approval.py` (6 tests). Full suite: 370 passed.

## Not completed (remaining)
- [ ] P5-a: Optional Agno + LiteLLM agent-runtime migration. Both deps are absent (verified),
      so this starts with adding them, then a new runtime adapter (e.g.
      `app/services/agents/runtime_agno.py`) behind the existing agent interface — existing
      agents keep working, nothing is removed. Tests: `tests/test_agent_runtime_agno.py`.
- [x] P5-b: Agent-tool specific order approval — DONE (see Completed above).
- [ ] P5-c: Voice / attachments / web-search / skills in the agent runtime (deferred items,
      each behind its own config flag).

## Files touched
- `backend/app/services/mcp/client.py`
- `backend/app/services/agents/chart_markup.py`
- `backend/app/api/routers/mcp_client.py` (`/api/mcp/clients`)
- `backend/app/api/routers/chart_markup.py` + `analysis.py` (chart-markup routes)
- `backend/app/api/routers/research.py` (`/api/llm/registry`) and `trading.py`
  (`/trading/model-registry`)
- `backend/tests/test_mcp_client.py`
- `backend/tests/test_chart_markup.py`
- `backend/tests/test_model_registry.py`
- `frontend/app/ai-tools/page.tsx`
