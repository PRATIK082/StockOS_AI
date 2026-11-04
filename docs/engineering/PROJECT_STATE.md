# Project State — StockOS AI

## Branch / Revision
- Active work branch: `feature/flow-strategy-suite` (from `origin/main` @ `a58ba47`, the merged PR #4).
- `main` includes everything through S4 streaming (PR #4 merged as `a58ba47`).
- Spec branch `feature/agentic-platform-spec` pushed (spec doc only, `95e51f8`).
- Standing rule: local commits; push only on explicit user confirmation.

## Completed (all merged to main via PR #4)
- S1 E2E harness + Phase 4 approval E2E (Playwright, 8/8 green with S4 specs).
- S2 Phase 9 ops: monitoring, calendar, PnL, Telegram read-only, broker diagnostics (backend + pages).
- S3 Phase 5: P5-b agent-tool approval, P5-a Agno+LiteLLM (env-flagged, legacy default), P5-c voice/attachments/websearch/skills.
- S3.5 streaming: poll hub + WS/REST + pages + E2E. Backend pytest 404 passed; typecheck + build green.

## In progress — team self-team-1 (spawned 2026-11-04)
Goal: all remaining work-plan items (S4 Flow F-7, S5 strategy host F-8, S6 polish F-10).
- `flow-backend` (bgt): backend/app/services/flow/*, routers/flow.py, models/flow_graph.py, tests/test_flow.py.
- `flow-ui` (bgt): frontend/app/flow/* (list + [id] builder, @xyflow/react).
- `strat-ui` (bgt): frontend/app/strategies/* (list + [id] editor, CodeMirror).
- `host-backend` (queued): runs after flow-backend lands (test-DB safety); services/strategy_host/*, router, model, tests.
- Parent owns: shared-file wiring (routers/__init__.py, models/__init__.py, navigation.tsx), full pytest + typecheck + build + E2E, commits.
- `qa-polish` (queued last): E2E specs for flow/strategies, docs checkboxes, secrets audit (F-10 subset).

## Conventions (binding on all agents)
- Backend tests: temp-DB conftest + module TestClient + register/auth fixtures; class-level MarketDataService patches ONLY (never instance-level); PaperBroker class-state isolation fixture when filling paper orders.
- Approval semantics: REQUIRE_APPROVAL → ActionCenterItem, zero direct fills; paper-only defaults; no fabricated market data.
- Frontend: `api` from @/lib/api (no /api prefix), React Query v5, shadcn, amber warnings; no git/build/dev-server commands from builders.

## Remaining / Next
- S4 Flow builder, S5 strategy host, S6 polish (this team).
- Agentic-platform-spec F-01..F-12 features: spec'd, awaiting approval — NOT in scope for this team.
- Local-only files (never commit): `demo.mjs`, `opencode.json`.
