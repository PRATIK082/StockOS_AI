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
- [x] P5-a: Agno + LiteLLM agent-runtime migration. Deps pinned
      (`agno>=2.9,<3`, `litellm>=1.106.6,<2`, `mcp>=2.3,<3` — litellm 1.106+
      imports the `mcp` package, verified by a live failure). New
      `LiteLLMProvider` (`app/services/llm/providers/litellm_provider.py`,
      lazy import, clean RuntimeError when absent) registered in the gateway
      as `litellm` (Ollama base + OpenAI key defaults, zero new settings).
      New opt-in runtime `app/services/agents/runtime_agno.py`
      (`STOCKOS_AGENT_RUNTIME=agno`, default legacy): legacy evidence pass
      first, then one Agno tool-calling pass (P5-b preview/place tools;
      place without a user returns a not-placed message, never raises), any
      failure falls back to the legacy result. Orchestrator `_run` routes
      through `run_agent` (default behavior byte-identical). Verified live:
      Agno 2.9.0 + LiteLLM instantiate in-process, `acompletion` and Agno
      tool-calling work against local Ollama (qwen3:14b; ministral-3:14b hit
      a model-side repeat-limit, environmental).
      Tests: `tests/test_agent_runtime_agno.py` (13 tests, all faked, no
      network). Full suite: 383 passed.

## Not completed (remaining)
- [x] P5-a: Agno + LiteLLM agent-runtime migration — DONE (see Completed above).
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
