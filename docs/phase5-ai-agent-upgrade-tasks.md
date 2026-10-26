# Phase 5 — AI Agent Upgrade: Concrete Implementation Tasks

Branch: `feature/openalgo-adaptation` (local only)

## Already available in StockOS
- [x] Multi-agent research/analysis services (`app/services/agents/*`).
- [x] MCP server exposing 62 StockOS tools (`app/services/mcp/*`).
- [x] Action Center approval queue for orders (`app/services/action_center.py`, router).
- [x] Provider/model registry endpoint (`/api/trading/providers`).

## Pending
- [ ] Add MCP client to consume external MCP servers.
- [ ] Add agent -> chart markup integration.
- [ ] Add voice/attachments/web-search/skills to agent runtime.
- [ ] Add Agno/LiteLLM runtime adapter (optional; keep existing agents working).
- [ ] Add end-to-end tests for agent tool execution + approval.
