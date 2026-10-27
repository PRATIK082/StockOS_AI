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
- [x] Frontend surfaces for MCP clients, chart markup, and model registry
      (`frontend/app/ai-tools/page.tsx`).
- [ ] Agent-tool specific order approval (the generic Action Center queue exists and
      is wired, but the agent runtime does not yet route its tool calls through it).
- [ ] Voice / attachments / web-search / skills in the agent runtime.

## Phase 6 — Options Suite (added)
Completed in Phase 6:
- [x] Options analytics service (`app/services/options/analytics.py`): max pain, OI
      profile, OI change, IV smile + 25-delta skew, volatility surface + ATM term
      structure, gamma exposure (zero-gamma / flip strike), straddle payoff.
- [x] Margin calculator + synthetic futures (`app/services/options/margin.py`) with a
      transparent leverage table; every response is flagged `is_estimate: true`.
- [x] Routers: `/api/options/analytics/*` and `/api/options/margin/*`.
- [x] Frontend page `frontend/app/options-analytics/page.tsx` (table-based; the Plotly
      dependency was skipped on purpose — no new npm dependency without approval).
- [x] Tests: `backend/tests/test_options_phase6.py` (34 tests).

Known behaviour:
- The free TradingView options scanner publishes no open interest, so max pain, OI
  profile and GEX legitimately return empty values for those chains.
- A chain expiring today (0DTE) has no time value, so the 25-delta skew is reported as
  unavailable instead of being filled with a proxy number.
- When a chain carries no OI, support/resistance and zero-gamma/flip levels are
  returned as null (not the first strike of the grid) with an explanatory note.
- When a chain publishes no option premium, the straddle endpoint returns
  `has_premium: false`, an empty breakeven list and null max profit/loss; only the
  expiry intrinsic curve is shown. The synthetic-futures endpoint adds a note that
  it was costed at zero premium.
