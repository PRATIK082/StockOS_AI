# Reference Platform -> StockOS AI: Deep Comparative Study and Implementation Plan

> **Purpose**: This document is the single source of truth for learning from
> the external reference platform and adapting
> its architecture, capabilities, and UI patterns into **StockOS AI**.
> It intentionally contains **no cloned code or files**. All references point to
> the upstream project for study; implementation in StockOS must be rewritten
> and integrated with StockOS conventions (FastAPI + Next.js App Router).
>
> **Study source**: `the external reference platform` (cloned to a
> temporary directory for analysis only; not vendored into this repository).
> **Reference Platform version studied**: `2.0.1.4` (Python >= 3.12, Node >= 22/24/26).
> **StockOS base**: `feature/demo-media` (commit `955cd63` on top of `main`
> `e4cbbbd`).
>
> **How to use**: Read sections 1-4 for orientation, section 5 for subsystem
> depth, section 6 for prioritized value-adds, section 7 for the phased
> implementation plan, section 8 for file/module mapping, section 9 for risks.

---

## 1. Executive Summary

Reference Platform is a **broker-centric, multi-broker algorithmic trading platform**
(Flask + React/Vite). StockOS AI is an **AI-first research and paper-trading
platform** (FastAPI + Next.js). They are complementary:

- Reference Platform excels at **broker connectivity, normalized order APIs, real-time
  WebSocket streaming, visual strategy building, Python strategy hosting,
  options analytics, analyzer mode, action center, and operational security**.
- StockOS excels at **AI agent orchestration, self-learning memory, multi-agent
  autopilot, factor research, backtesting, risk x-ray, and a unified Terminal
  Command Center**.

**Recommendation**: Do **not** merge or clone Reference Platform. Instead, treat it as a
reference architecture and selectively port its **patterns and capabilities**
into StockOS, preserving StockOS's AI-first identity and FastAPI/Next.js stack.
The highest-leverage adoptions are:

1. **Broker plugin contract + master contract store** (multi-broker foundation).
2. **Unified broker REST API surface** (`/api/v1`-style normalized methods).
3. **Analyzer Mode + Action Center** (safe pre-live execution + human approval).
4. **Historify (DuckDB) market-data warehouse** (columnar, multi-interval).
5. **Flow visual strategy builder** (xyflow/React Flow, already a StockOS dep).
6. **Python strategy host (OpenScript)** (process isolation + scheduling).
7. **Options analytics suite** (12 tools, Plotly + lightweight-charts).
8. **Agentic AI stack upgrades** (Agno + LiteLLM + MCP + tool approval).
9. **Security hardening** (Argon2, Fernet, CSRF, rate limits, CSP, TOTP).
10. **Monitoring dashboards** (latency, traffic, health, PnL tracker).

---

## 2. Method and Scope

### 2.1 Study method

- Cloned Reference Platform to a **temporary** directory outside the project for
  read-only analysis. No Reference Platform files were copied into StockOS.
- Indexed Reference Platform with the codebase knowledge graph (fast mode) and queried
  architecture, routes, clusters, and symbols.
- Read key source files directly for implementation details.
- Cross-referenced StockOS files and routes.

### 2.2 Reference Platform at a glance

| Dimension | Reference Platform |
|---|---|
| Backend | Flask 3.1, Flask-RESTX, Flask-SocketIO, SQLAlchemy 2, APScheduler, DuckDB, ZeroMQ |
| Frontend | React 19, Vite 8, TypeScript, Tailwind 4, shadcn/ui, TanStack Query, Zustand, CodeMirror, xyflow, Plotly, lightweight-charts |
| Brokers | 36 plugins (35 Indian securities + Delta Exchange crypto) |
| REST API | 57 `/api/v1` method/path pairs |
| Blueprint routes | ~442 Flask blueprint routes + 1 app route |
| Databases | 6 (main, logs, latency, health, sandbox, Historify DuckDB) |
| AI | Agno agent + LiteLLM; MCP server; tool approval |
| Strategy | Flow (xyflow), Python host (process isolation), ChartInk webhooks |
| Options tools | 12 (Strategy Builder, Option Chain, IV Smile, Max Pain, Vol Surface, GEX, OI Tracker, OI Profile, Straddle Chart, Straddle PnL, IV Chart, Option Greeks) |
| Security | Argon2, Fernet (PBKDF2), CSRF, rate limiting, CSP, IP ban, TOTP, session expiry |
| Notifications | Telegram, WhatsApp |
| Monitoring | Latency, traffic, health, PnL tracker |

### 2.3 StockOS at a glance

| Dimension | StockOS AI |
|---|---|
| Backend | FastAPI, SQLAlchemy, Alembic, APScheduler (cron), uvicorn |
| Frontend | Next.js (App Router), TypeScript, Tailwind, custom components |
| Brokers | Paper, Zerodha, AngelOne (gated adapters) + vendored TradingAgents |
| API | FastAPI routers (`/api` style, ~20+ routers) |
| Databases | Single SQLite (main) + optional local data |
| AI | Multi-agent (base/chat/fundamental/momentum/research/technical/stock_analysis/swarm), autopilot, learning memory |
| Strategy | Backtesting (v1/v2, portfolio, sandbox), factors (Alpha101), scheduled runs |
| Options | Options engine + signals + quantlib |
| Security | JWT/bearer (security.py), CORS env-configurable, basic |
| Monitoring | Limited (health endpoints) |
| Notifications | None built-in |

---

## 3. High-Level Architecture Comparison

| Area | Reference Platform | StockOS | Verdict |
|---|---|---|---|
| Runtime model | Self-hosted Flask monolith + React SPA served from `frontend/dist` | FastAPI + Next.js (separate dev servers) | Keep StockOS split; adopt Reference Platform's single-origin serving option for prod |
| Broker integration | Plugin contract (`plugin.json` + `api/*.py`) with lazy auth import | Hand-written adapters (`brokers/*.py`) | Adopt plugin contract to scale brokers |
| Master data | Per-broker master contract DBs + symbol metadata | Universe/instruments routers | Adopt master contract store |
| Market data store | DuckDB (Historify) + SQLite (main) | OHLCV service + providers | Adopt DuckDB warehouse |
| Real-time | ZMQ-based WebSocket proxy (port 8765) | Polling/best-effort | Adopt streaming later (Phase 4) |
| Auth | Session + API key (Argon2 + Fernet), TOTP | JWT + bearer | Strengthen StockOS auth with Argon2/Fernet/TOTP |
| Security headers | CSP, HSTS-like, IP ban, rate limits | CORS only | Port security middleware |
| Strategy execution | Flow builder + Python host + ChartInk | Backtesting + autopilot + scheduled | Add Flow + Python host |
| AI agent | Agno + LiteLLM + MCP + tool approval + chart markup | Custom agents + chat + autopilot | Upgrade to Agno/LiteLLM/MCP |
| Order safety | Analyzer Mode + Action Center (semi-auto) | Paper mode + risk engine | Add analyzer + action center |
| Monitoring | Latency/traffic/health/PnL dashboards | Minimal | Add dashboards |
| Notifications | Telegram + WhatsApp | None | Add Telegram (high value) |
| Options analytics | 12 dedicated tools | Options page + engine | Expand to tool suite |

---

## 4. Capability Matrix (Reference Platform vs StockOS)

Legend: ✅ strong, 🟡 partial, ❌ absent.

| Capability | Reference Platform | StockOS | Gap / Opportunity | Priority |
|---|---|---|---|---|
| Multi-broker (36) | ✅ | 🟡 (3) | Broker plugin contract | P1 |
| Normalized order API | ✅ | 🟡 | Unified `/api/v1`-style methods | P1 |
| GTT orders | ✅ (Dhan/Zerodha) | ❌ | Add GTT support | P3 |
| Basket/smart/split orders | ✅ | ❌ | Add order workflows | P2 |
| Real-time WebSocket streaming | ✅ (ZMQ proxy) | ❌ | Streaming layer | P2 |
| Analyzer Mode (sandbox) | ✅ | 🟡 (paper) | Full analyzer with margin | P1 |
| Action Center (approval) | ✅ | ❌ | Human-in-the-loop orders | P1 |
| Historify (DuckDB warehouse) | ✅ | ❌ | Columnar market data | P1 |
| Flow visual builder | ✅ | ❌ | xyflow already available | P2 |
| Python strategy host | ✅ | ❌ | Process isolation + schedule | P2 |
| ChartInk webhooks | ✅ | ❌ | External signal ingestion | P3 |
| Options tool suite (12) | ✅ | 🟡 (1 page) | Expand analytics pages | P2 |
| AI agent (Agno/LiteLLM) | ✅ | 🟡 (custom) | Upgrade agent runtime | P1 |
| MCP server | ✅ | 🟡 (service exists) | Expose StockOS as MCP | P2 |
| Tool approval in agent | ✅ | ❌ | Order approval UX | P1 |
| Chart markup by agent | ✅ | ❌ | Agent -> chart integration | P2 |
| 127 indicators (Rust indicator library) | ✅ | 🟡 (Python lib) | Rust indicator backend | P3 |
| Security (Argon2/Fernet/CSRF/etc.) | ✅ | 🟡 | Harden auth/security | P1 |
| Rate limiting | ✅ | ❌ | Add limiter | P1 |
| CSP/IP ban/TOTP | ✅ | ❌ | Security middleware | P2 |
| Monitoring dashboards | ✅ | ❌ | Latency/traffic/health/PnL | P2 |
| Telegram notifications | ✅ | ❌ | Add Telegram bot | P2 |
| WhatsApp notifications | ✅ | ❌ | Optional | P3 |
| Market calendar | ✅ | 🟡 | Calendar service | P2 |
| Scalping/arbitrage tools | ✅ | ❌ | Optional trading tools | P3 |
| Portfolio/SIP backtesting | ✅ | 🟡 | Extend backtest | P3 |
| Factor research (Alpha101) | ❌ | ✅ | StockOS strength; keep |
| AI autopilot missions | ❌ | ✅ | StockOS strength; keep |
| Self-learning memory | ❌ | ✅ | StockOS strength; keep |
| Terminal Command Center | 🟡 | ✅ | StockOS strength; keep |

---

## 5. Deep-Dive Subsystems

### 5.1 Broker Plugin Contract and Master Contract

**Reference Platform implementation**

- Directory: `broker/<broker>/` with `plugin.json`, `api/*.py`, `mapping/*.py`,
  `streaming/*.py`, `database/master_contract_db.py`.
- `utils/plugin_loader.py` loads `plugin.json` capabilities lazily and lazily
  imports `broker.<name>.api.auth_api.authenticate_broker` only at login.
- Capabilities include `supported_exchanges`, `broker_type`, `leverage_config`.
- Master contract stores symbols/expiries/underlyings and is queried by
  Historify and option chain tools.

**StockOS current**

- `backend/app/brokers/{angelone,zerodha,paper,interface}.py` hand-written.
- `backend/app/services/data/providers/*` for market data.
- `instruments_new.py` router.

**Adaptation**

- Introduce `backend/app/brokers/<name>/` package with `plugin.json`,
  `api/auth_api.py`, `api/order_api.py`, `api/data.py`, `mapping/`.
- Add a `plugin_loader.py` equivalent in StockOS.
- Add `master_contract` tables (symbol, exchange, expiry, underlying,
  instrument_type, lot size).
- Keep existing adapters as first plugins (`paper`, `zerodha`, `angelone`).

**Effort**: L. **Risk**: High (touches order routing). **Mitigation**: Start
with paper + one live broker, keep paper default.

### 5.2 Unified Broker REST API

**Reference Platform implementation**

- Flask-RESTX namespace `/api/v1` with 57 endpoints (place/modify/cancel order,
  smart order, basket, split, GTT, quotes, depth, history, option chain,
  greeks, funds, positions, holdings, order/trade book, search, symbol,
  margin, synthetic future, expiry, intervals, analyzer toggle, Telegram).
- Schemas centralized in `restx_api/schemas.py` and `data_schemas.py`.
- Constants in `utils/constants.py`.

**StockOS current**

- FastAPI routers per domain (`orders`, `portfolio`, `market`, `options`,
  `trading`, etc.) with Pydantic schemas in `api/schemas.py`.

**Adaptation**

- Add a `backend/app/api/routers/broker_api.py` (or `broker_compat.py`)
  exposing normalized broker methods, initially backed by StockOS brokers.
- Define Pydantic request/response models matching Reference Platform field names for
  external compatibility (TradingView/Amibroker/ChartInk).
- Keep StockOS-native routers for AI/research features.

**Effort**: M. **Priority**: P1 for external integration, P2 for UI.

### 5.3 Real-Time WebSocket Streaming

**Reference Platform implementation**

- Separate WebSocket proxy (port 8765) using ZeroMQ message bus.
- Brokers implement streaming adapters (`broker/<name>/streaming/`).
- Frontend subscribes to LTP/Quote/Depth.

**StockOS current**

- Polling-based market data; `TerminalProvider` loads snapshots.

**Adaptation**

- Phase 4: Add optional streaming service (FastAPI WebSocket or separate
  process) with ZMQ/Redis pub-sub. Keep polling as fallback.

**Effort**: XL. **Priority**: P3.

### 5.4 Auth and Security Hardening

**Reference Platform implementation**

- `database/auth_db.py`: Argon2 password hashing with pepper; Fernet token
  encryption with PBKDF2 + per-install salt; API keys hashed + encrypted for
  retrieval; verification cache; order mode per API key (`auto`/`semi_auto`).
- `cors.py`: env-controlled CORS, origins list, credentials toggle.
- `csp.py`: full CSP + security headers, IP ban middleware, rate limiter
  (`limiter.py`), TOTP 2FA, session expiry at 03:00 IST, CSRF (session
  routes; `/api/v1` exempt).

**StockOS current**

- `core/security.py`, JWT/bearer; CORS now env-configurable (already improved).
- No Argon2/Fernet/TOTP/rate limit/CSP/IP ban.

**Adaptation**

- Add Argon2 password hashing + Fernet token encryption in StockOS auth.
- Add slowapi-style rate limiting to FastAPI.
- Add security headers middleware (CSP, X-Frame-Options, etc.).
- Add TOTP (pyotp) for 2FA.
- Add session expiry + broker token revocation.

**Effort**: M. **Priority**: P1 (security).

### 5.5 Multi-Database Architecture

**Reference Platform implementation**

- 6 SQLite/DuckDB databases: main, logs, latency, health, sandbox, Historify.
- `NullPool` to avoid FD leaks; scoped sessions removed on teardown.
- Separate DB URLs via env.

**StockOS current**

- Single SQLite main DB; Alembic migrations.

**Adaptation**

- Split logs/latency/health into separate DBs only if needed; start with
  main + optional analytics DB.
- Adopt `NullPool` and scoped session teardown in `db/session.py`.

**Effort**: S-M. **Priority**: P2.

### 5.6 Historify (DuckDB Market Data Warehouse)

**Reference Platform implementation**

- `database/historify_db.py` + `services/historify_service.py`.
- Stores OHLCV in DuckDB; storage intervals `1m`/`D`; computed intervals
  aggregated on the fly.
- Watchlist, data catalog, download jobs with pause/resume/cancel/checkpoint,
  incremental downloads, zombie job cleanup, ThreadPoolExecutor.
- CSV/Parquet import/export.
- FNO discovery (underlyings, expiries, chains, futures).
- Socket.IO progress.

**StockOS current**

- OHLCV providers + service; no persistent warehouse; no download jobs.

**Adaptation**

- Add `backend/app/services/historify/` with DuckDB store + download jobs.
- Add routers `/historify/*` and frontend Historify page.
- Reuse StockOS providers for fetch; store in DuckDB.

**Effort**: L. **Priority**: P1 (data foundation for backtesting/AI).

### 5.7 Options Analytics Suite

**Reference Platform implementation**

- 12 pages: Strategy Builder (multi-leg, payoff, Greeks, what-if, basket
  execution), Strategy Portfolio, Option Chain, IV Chart, OI Tracker, Max
  Pain, Straddle Chart, Straddle PnL, Vol Surface, GEX Dashboard, IV Smile,
  OI Profile.
- Services: `option_chain_service`, `option_greeks_service`,
  `gex_service`, `vol_surface_service`, `straddle_chart_service`, etc.
- Uses Plotly + lightweight-charts.

**StockOS current**

- `options` page + engine + signals + quantlib.

**Adaptation**

- Port option analytics services to StockOS (Python) and add pages under
  `frontend/app/options/*` or `frontend/app/tools/*`.
- Reuse StockOS options engine; add Plotly dependency.

**Effort**: L. **Priority**: P2.

### 5.8 Flow Visual Strategy Builder

**Reference Platform implementation**

- `frontend/src/pages/flow/*` + `services/flow_executor_service.py`,
  `flow_workflow_validator.py`, `flow_scheduler_service.py`,
  `flow_price_monitor_service.py`, `flow_order_update_monitor_service.py`.
- xyflow/React Flow nodes: market data, indicators, conditions, orders,
  notifications; webhook triggers; JSON import/export; visual debugging.

**StockOS current**

- No visual builder; has backtesting + autopilot.

**Adaptation**

- Add `frontend/app/flow` pages using `@xyflow/react` (already? check StockOS
  deps; not currently; add).
- Backend: flow graph validator + executor that calls StockOS market/order
  services; scheduler integration.

**Effort**: XL. **Priority**: P2.

### 5.9 Python Strategy Host (OpenScript)

**Reference Platform implementation**

- `blueprints/python_strategy.py`, `services/openscript_*.py`.
- CodeMirror editor, process isolation (multiprocessing), IST scheduling,
  env var encryption, real-time logs via Socket.IO, state persistence.

**StockOS current**

- Scheduled runs + backtesting; no hosted Python strategies.

**Adaptation**

- Add `backend/app/services/strategy_host/` with process runner + scheduler.
- Frontend CodeMirror editor page.

**Effort**: L. **Priority**: P2.

### 5.10 AI Agent (Agno + LiteLLM + MCP)

**Reference Platform implementation**

- `services/agent/*`: Agno framework, LiteLLM provider layer, MCP client,
  tool catalog (account, chart, indicators, instrument, live, market, options,
  orders, symbols, viz, websearch, flow generation, strategy generation,
  openscript generation, skills), safety/risk audit, chart geometry/markup,
  voice, attachments, streaming.
- Frontend `pages/agent/*` + components (composer, messages, tool timeline,
  model picker, viz).
- Every order pauses for approval; risk limits applied after approval.
- Supports ChatGPT OAuth, Ollama, any LiteLLM provider.

**StockOS current**

- Custom agents (`services/agents/*`), chat, autopilot, swarm, MCP server
  service, LLM gateway.

**Adaptation**

- Migrate StockOS agent runtime to Agno + LiteLLM (or adapt patterns) to
  gain tool catalog, MCP client, approval flow, chart markup.
- Add tool approval UI and risk guard before order execution.
- Keep StockOS self-learning memory as an agent tool.

**Effort**: L-XL. **Priority**: P1 (core differentiator).

### 5.11 Analyzer Mode (Sandbox)

**Reference Platform implementation**

- `services/analyzer_service.py`, `sandbox_service.py`, `sandbox_db.py`.
- Sandbox capital (~1.1 Cr), realistic margin, square-off schedules,
  separate DB, supports core price types.

**StockOS current**

- Paper broker + risk engine; no sandbox capital/margin simulation.

**Adaptation**

- Enhance paper broker with configurable sandbox capital, margin, and
  square-off schedules; separate DB or schema.

**Effort**: M. **Priority**: P1.

### 5.12 Action Center (Human Approval)

**Reference Platform implementation**

- `database/action_center_db.py`, `blueprints/orders.py` approval endpoints.
- Order mode `auto`/`semi_auto` per API key; pending orders with approve/
  reject + audit trail (IST).

**StockOS current**

- No approval queue.

**Adaptation**

- Add `action_center` table + service + endpoints.
- Route orders through approval queue when semi-auto mode.
- Frontend Action Center page.

**Effort**: M. **Priority**: P1 (safety for AI orders).

### 5.13 MCP Server

**Reference Platform implementation**

- `mcp/mcpserver.py` (large) + `blueprints/mcp_http.py`, `mcp_oauth.py`,
  admin remote MCP page; exposes trading tools to Claude/Cursor/etc.

**StockOS current**

- `services/mcp/server.py` + tools + `__main__.py`.

**Adaptation**

- Compare Reference Platform MCP tool catalog and auth (OAuth) to StockOS MCP; add
  missing tools (positions, funds, option chain) and OAuth if needed.

**Effort**: M. **Priority**: P2.

### 5.14 Monitoring Dashboards

**Reference Platform implementation**

- Latency monitor (round-trip times), traffic monitor (API usage/errors),
  health monitor (FD/memory/DB/WS/threads), PnL tracker (lightweight-charts).

**StockOS current**

- Minimal health endpoints.

**Adaptation**

- Add middleware to record request latency/traffic; health metrics collector;
  frontend dashboards.

**Effort**: M. **Priority**: P2.

### 5.15 Notifications (Telegram/WhatsApp)

**Reference Platform implementation**

- Telegram bot service + blueprint + frontend config/users/analytics.
- WhatsApp notify endpoint.

**StockOS current**

- None.

**Adaptation**

- Add Telegram bot service (python-telegram-bot) with order alerts and
  command menu; optional WhatsApp.

**Effort**: M. **Priority**: P2 (Telegram), P3 (WhatsApp).

### 5.16 ChartInk Integration

**Reference Platform implementation**

- `blueprints/chartink.py`, `pages/chartink/*`: webhook alerts with BUY/SELL/
  SHORT/COVER, intraday square-off, bulk symbols CSV.

**StockOS current**

- No external scanner webhooks (has internal scanners).

**Adaptation**

- Add webhook endpoint + mapping to StockOS order service; UI for symbol
  configuration.

**Effort**: S-M. **Priority**: P3.

### 5.17 Frontend Architecture

**Reference Platform implementation**

- React 19 + Vite 8 + React Router 7 + TanStack Query + Zustand + shadcn/ui
  (Radix) + Tailwind 4 + CodeMirror + xyflow + Plotly + lightweight-charts +
  Socket.IO client + Biome lint.

**StockOS current**

- Next.js App Router + Tailwind + custom components; no TanStack Query/Zustand/
  shadcn/xyflow/Plotly (some?).

**Adaptation**

- Adopt shadcn/ui component library in StockOS (Radix-based) for consistency.
- Add TanStack Query for server state caching.
- Add Plotly for options viz; xyflow for Flow builder; CodeMirror for strategy
  editor.
- Keep Next.js (better for StockOS) rather than Vite.

**Effort**: M. **Priority**: P2 (UI polish).

### 5.18 Market Calendar and Schedulers

**Reference Platform implementation**

- `services/market_calendar_service.py`, admin holidays/timings; APScheduler.

**StockOS current**

- `market_session.py`, scheduler service/cron/runner.

**Adaptation**

- Enhance with holiday calendar and market timings endpoints.

**Effort**: S. **Priority**: P3.

---

## 6. Value-Add Prioritization

### Tier 1 (High impact, foundation) — do first
1. Security hardening (Argon2/Fernet/rate limit/CSP/TOTP/session).
2. Broker plugin contract + master contract store.
3. Historify (DuckDB warehouse).
4. Analyzer Mode + Action Center.
5. AI agent upgrade (Agno/LiteLLM + tool approval + MCP client).

### Tier 2 (Product expansion)
6. Options analytics suite (12 tools).
7. Flow visual strategy builder.
8. Python strategy host.
9. Monitoring dashboards.
10. Telegram notifications.
11. Frontend component library (shadcn) + TanStack Query.
12. Real-time WebSocket streaming (needed for live trading parity).
13. Smart/basket/split order workflows + position sizing.
14. Margin calculator + synthetic futures.
15. Market calendar, holidays, timings admin.
16. Broker TOTP/auth flows + admin diagnostics.

### Tier 3 (Nice-to-have / specialized)
17. ChartInk webhooks.
18. GTT orders.
19. Scalping/arbitrage tools.
20. WhatsApp notifications.
21. Rust indicator backend.

---

## 7. Implementation Plan

### Phase 0 - Preparation (1 week)
- [x] Create branch `StockAlgo_1` from `main`.
- [x] Add this document to repo (done).
- [x] Add dependency list updates (`argon2-cffi`, `cryptography`, `duckdb`,
      `slowapi`, `pyotp`, `python-telegram-bot`, `agno`, `litellm`,
      `@xyflow/react`, `plotly.js`, `@uiw/react-codemirror`, shadcn).
- [x] Define `broker/` plugin directory convention in StockOS.

### Phase 1 - Security and Auth (2-3 weeks)
- [x] Implement Argon2 password hashing + pepper in `core/security.py`.
- [x] Implement Fernet token encryption with per-install salt.
- [x] Add rate limiting middleware (slowapi) to FastAPI.
- [x] Add security headers middleware (CSP, X-Frame-Options, etc.).
- [x] Add TOTP 2FA endpoints + UI.
- [x] Add session expiry + broker token revocation.
- [x] Tests: auth security unit + integration.

### Phase 2 - Broker Plugin Contract (3-4 weeks)
- [x] Create `backend/app/brokers/<name>/plugin.json` for paper/zerodha/angelone.
- [x] Add `plugin_loader.py` (lazy auth import).
- [x] Refactor existing adapters to implement common interface.
- [x] Add master contract tables + service + router.
- [x] Tests: plugin loading + master contract.

### Phase 3 - Historify Market Data Warehouse (3-4 weeks)
- [x] Add DuckDB integration (`services/historify/`).
- [x] Implement watchlist, catalog, download jobs (pause/resume/cancel).
- [x] Add incremental downloads + zombie cleanup.
- [x] Add CSV/Parquet import/export.
- [x] Add FNO discovery (underlyings/expiries/chains).
- [x] Add `/historify/*` routers + frontend page. (routers + `frontend/app/historify/page.tsx` done)
- [x] Tests: DuckDB store + job lifecycle.

### Phase 4 - Analyzer Mode + Action Center (2-3 weeks)
- [x] Enhance paper broker with sandbox capital/margin/square-off.
- [x] Add action center table + service + endpoints.
- [x] Route orders through approval queue in semi-auto mode.
- [x] Add smart/basket/split order workflows + position sizing.
- [x] Add frontend Action Center page + approval UX. (`frontend/app/action-center/page.tsx`,
      approve → execute two-step flow + analyzer-mode card)
- [x] Tests: approval flow.

### Phase 5 — AI Agent Upgrade (4-6 weeks)
- [ ] Migrate agent runtime to Agno + LiteLLM (or adapt).
- [x] Add MCP client to consume external tools. (`app/services/mcp/client.py` — stdio + SSE,
      `/api/mcp/clients*` routes)
- [ ] Add tool approval flow for orders. (generic Action Center queue exists; agent-tool
      specific approval still pending)
- [x] Add chart markup integration (agent -> chart). (`app/services/agents/chart_markup.py`,
      `/api/analysis/chart-markup` + `/api/chart-markup`)
- [x] Add model registry UI (providers/models). (`/api/llm/registry`,
      `/api/trading/model-registry`, `frontend/app/ai-tools/page.tsx`)
- [x] Tests: agent tool execution + approval. (`test_mcp_client.py`, `test_chart_markup.py`,
      `test_model_registry.py`)

### Phase 6 — Options Suite (3-4 weeks)
- [x] Port option analytics services (GEX, vol surface, IV smile, OI
      tracker/profile, straddle chart/PnL, max pain).
      (`app/services/options/analytics.py` + `/api/options/analytics/*`)
- [x] Add margin calculator + synthetic futures endpoints.
      (`app/services/options/margin.py` + `/api/options/margin/*`)
- [x] Add options analytics frontend page. (`frontend/app/options-analytics/page.tsx` —
      table-based rendering; Plotly dependency deliberately deferred to avoid an
      unapproved new dependency)
- [x] Tests: option analytics. (`test_options_phase6.py`, 34 tests)

### Phase 7 — Flow Builder (4-6 weeks)
- [ ] Add xyflow dependency.
- [ ] Implement flow graph validator + executor.
- [ ] Add frontend Flow pages.
- [ ] Integrate scheduler.

### Phase 8 — Python Strategy Host (3-4 weeks)
- [ ] Process isolation runner + scheduler.
- [ ] CodeMirror editor page.
- [ ] Env var encryption + logs.

### Phase 9 — Monitoring + Notifications (2-3 weeks)
- [ ] Latency/traffic/health middleware + dashboards.
- [ ] PnL tracker page.
- [ ] Telegram bot service + UI.
- [ ] Market calendar, holidays, timings admin pages.
- [ ] Broker TOTP/auth flows + admin diagnostics.

### Phase 10 — Polish and Hardening (2 weeks)
- [ ] E2E tests, performance, security review.
- [ ] Documentation + demo update.

**Total estimated**: ~30-40 weeks for full parity; Tier 1+2 in ~20 weeks.

### 7.1 "No clone" implementation rules
- Rewrite all code in StockOS style (FastAPI, Pydantic, Next.js).
- Do not copy Reference Platform files verbatim.
- Adapt naming to StockOS conventions.
- Keep Reference Platform as reference only; cite file paths in PRs.
- Preserve StockOS AI-first differentiators.

---

## 8. File/Module Mapping (Reference Platform -> StockOS)

| Reference Platform path | StockOS target | Action |
|---|---|---|
| `utils/plugin_loader.py` | `backend/app/brokers/plugin_loader.py` | Adapt |
| `broker/*/plugin.json` | `backend/app/brokers/*/plugin.json` | Adapt |
| `broker/*/api/*.py` | `backend/app/brokers/*/api/*.py` | Adapt |
| `database/auth_db.py` | `backend/app/core/security.py` + auth | Adapt patterns |
| `cors.py`, `csp.py` | `backend/app/core/middleware.py` | Adapt |
| `limiter.py` | `backend/app/core/rate_limit.py` | Adapt |
| `database/historify_db.py` | `backend/app/services/historify/store.py` | Adapt |
| `services/historify_service.py` | `backend/app/services/historify/service.py` | Adapt |
| `database/action_center_db.py` | `backend/app/db/models/action_center.py` | Adapt |
| `services/analyzer_service.py`, `sandbox_service.py` | `backend/app/services/paper/analyzer.py` | Adapt |
| `services/agent/*` | `backend/app/services/agent/*` | Adapt/upgrade |
| `services/flow_*` | `backend/app/services/flow/*` | Adapt |
| `services/openscript_*` | `backend/app/services/strategy_host/*` | Adapt |
| `services/option_*`, `gex_service`, etc. | `backend/app/services/options/*` | Adapt |
| `mcp/mcpserver.py` | `backend/app/services/mcp/*` | Adapt |
| `blueprints/telegram.py` | `backend/app/api/routers/telegram.py` | Adapt |
| `frontend/src/pages/flow/*` | `frontend/app/flow/*` | Adapt |
| `frontend/src/pages/agent/*` | `frontend/app/agent/*` | Adapt |
| `frontend/src/components/ui` (shadcn) | `frontend/components/ui` | Adopt |
| `frontend/src/pages/monitoring/*` | `frontend/app/monitoring/*` | Adapt |

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scope creep (36 brokers) | High | Start with 3 brokers; plugin contract first |
| DuckDB migration complexity | Medium | Incremental: keep SQLite, add DuckDB side-by-side |
| Agent migration breaks existing | High | Feature-flag new runtime; keep old until parity |
| Security changes break auth | High | Backward-compatible token migration |
| Frontend rewrite cost | High | Adopt components incrementally |
| Performance of streaming | Medium | Defer to Phase 4+ |
| Licensing/third-party | Low | Review each dependency license |

---

## 10. Verification and Test Plan

- Backend: pytest per module; target 300+ tests after additions.
- Frontend: typecheck + production build + Playwright E2E.
- Security: OWASP checklist, rate limit tests, CSP validation.
- Performance: load test historical download jobs.
- Browser: zero console errors on key pages.

---

## 12. Self-Sufficiency Checklist (No Reference Platform Dependency)

The following checklist ensures StockOS AI can fully replace Reference Platform for
day-to-day trading. Every Reference Platform capability must map to a StockOS
capability (existing or planned). Items marked **EXISTING** are already in
StockOS; **PLANNED** maps to phases above.

### 12.1 Broker connectivity and master data
- Broker plugin contract (36 brokers) — PLANNED (Phase 2)
- Lazy auth import — PLANNED (Phase 2)
- Master contract store (symbols/expiries/underlyings) — PLANNED (Phase 2)
- Broker TOTP/auth flows (Zerodha, Angel, Samco, etc.) — PLANNED (Phase 2/9)
- Leverage config (crypto brokers) — PLANNED (Phase 2)

### 12.2 Trading and orders
- Place/modify/cancel orders — EXISTING (orders router) + PLANNED (Phase 2)
- Smart orders with position sizing — PLANNED (Phase 4/7)
- Basket orders — PLANNED (Phase 4/7)
- Split orders — PLANNED (Phase 4/7)
- GTT orders — PLANNED (Tier 3)
- Margin calculator — PLANNED (Phase 6/7)
- Synthetic futures — PLANNED (Phase 6/7)
- Auto-split orders — PLANNED (Phase 4/7)
- Analyzer Mode (sandbox capital/margin) — PLANNED (Phase 4)
- Action Center (human approval) — PLANNED (Phase 4)
- Order mode auto/semi-auto — PLANNED (Phase 4)

### 12.3 Market data
- Real-time quotes/depth/history — EXISTING (market router) + PLANNED streaming
- Historify warehouse (DuckDB) — PLANNED (Phase 3)
- Download jobs (pause/resume/cancel) — PLANNED (Phase 3)
- Incremental downloads — PLANNED (Phase 3)
- CSV/Parquet import/export — PLANNED (Phase 3)
- FNO discovery (underlyings/expiries/chains) — PLANNED (Phase 3)
- WebSocket streaming (LTP/Quote/Depth) — PLANNED (Tier 2)

### 12.4 Strategy and automation
- Flow visual builder — PLANNED (Phase 7)
- Python strategy host — PLANNED (Phase 8)
- ChartInk webhooks — PLANNED (Tier 3)
- Scheduled runs — EXISTING (scheduled router)
- Backtesting (v1/v2/portfolio/SIP) — EXISTING + PLANNED extensions
- Autopilot missions — EXISTING (StockOS strength)

### 12.5 AI agent
- Agno + LiteLLM agent — PLANNED (Phase 5)
- MCP client + server — EXISTING (server) + PLANNED (client)
- Tool approval for orders — PLANNED (Phase 5)
- Chart markup by agent — PLANNED (Phase 5)
- Model registry (providers) — PLANNED (Phase 5)
- Voice/attachments/web search/skills — PLANNED (Phase 5)
- Self-learning memory — EXISTING (StockOS strength)

### 12.6 Options analytics
- Option chain — EXISTING + PLANNED expansion
- Option Greeks — EXISTING + PLANNED
- IV chart/smile — PLANNED (Phase 6)
- OI tracker/profile/range — PLANNED (Phase 6)
- Max pain — PLANNED (Phase 6)
- Straddle chart/PnL — PLANNED (Phase 6)
- Vol surface — PLANNED (Phase 6)
- GEX dashboard — PLANNED (Phase 6)
- Strategy builder (multi-leg) — PLANNED (Phase 6)
- Strategy portfolio — PLANNED (Phase 6)

### 12.7 Monitoring and ops
- Latency monitor — PLANNED (Phase 9)
- Traffic monitor — PLANNED (Phase 9)
- Health monitor — PLANNED (Phase 9)
- PnL tracker — PLANNED (Phase 9)
- Logs live — EXISTING/PLANNED

### 12.8 Notifications
- Telegram bot (alerts + commands) — PLANNED (Phase 9)
- WhatsApp notifications — PLANNED (Tier 3)

### 12.9 Security
- Argon2 + pepper — PLANNED (Phase 1)
- Fernet token encryption — PLANNED (Phase 1)
- Rate limiting — PLANNED (Phase 1)
- CSP + security headers — PLANNED (Phase 1)
- TOTP 2FA — PLANNED (Phase 1)
- IP ban — PLANNED (Phase 1)
- Session expiry + token revocation — PLANNED (Phase 1)
- CSRF — PLANNED (Phase 1)

### 12.10 Admin and misc
- Market calendar/holidays/timings — PLANNED (Phase 9/Tier 2)
- Freeze qty — PLANNED (admin)
- Diagnostics — PLANNED (admin)
- Remote MCP admin — PLANNED (admin)
- Scalping/arbitrage tools — PLANNED (Tier 3)
- Portfolio/SIP backtesting — EXISTING + PLANNED
- Portfolio analyzer — PLANNED

### 12.11 StockOS strengths (keep, not in Reference Platform)
- Factor research (Alpha101)
- AI autopilot missions
- Self-learning memory
- Terminal Command Center
- Multi-agent orchestration

**Conclusion**: With Phases 1–9 (Tier 1 + Tier 2) complete, StockOS AI reaches
functional parity for trading and exceeds Reference Platform in AI/agentic capabilities.
Tier 3 items are optional enhancements; none block full independence.

---

## 11. Open Questions

1. Should StockOS support external broker APIs for third-party clients, or
   remain internal-first?
2. Is DuckDB acceptable as a new dependency (size/licensing)?
3. Should agent migration replace or augment existing custom agents?
4. Which brokers to prioritize beyond paper/zerodha/angelone?
5. Do we need WhatsApp, or is Telegram sufficient?

---

## Appendix A — Reference Platform Route Inventory (summary)

- `/api/v1`: 57 REST method/path pairs (orders, portfolio, market data,
  options, funds, analyzer, telegram).
- Blueprint routes: ~442 (admin, agent, flow, historify, monitoring, python
  strategy, chartink, telegram, whatsapp, etc.).
- WebSocket proxy: port 8765 (ZMQ).

## Appendix B — StockOS Route Inventory (summary)

- FastAPI routers: analysis, auth, autopilot, instruments, market, memory,
  options, orders, portfolio, predictions, quant, quantlib, research,
  scheduled, settings, swarm, terminal, trading, watchlist.
- Next.js pages: home, trading/*, portfolio, prediction, options, scanner,
  screener, sectors, factors, intraday, chat, settings, etc.

## Appendix C — Key Reference Platform Dependencies

Flask 3.1, Flask-RESTX, Flask-SocketIO, SQLAlchemy 2, DuckDB, ZeroMQ,
Argon2-CFFI, Cryptography, Agno, LiteLLM, APScheduler, python-telegram-bot,
React 19, Vite 8, TanStack Query, Zustand, xyflow, Plotly, CodeMirror,
lightweight-charts, Tailwind 4, shadcn/ui (Radix), Biome, Playwright.

---

*Document generated from a read-only study of Reference Platform. No code or files from
Reference Platform were copied into StockOS. Implementations must be rewritten and
integrated per StockOS conventions.*

