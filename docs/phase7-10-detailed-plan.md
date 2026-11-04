# Phases 7–10 — Detailed Design and Implementation Plan

> Branch: `StockAlgo_1` (local; **no push until the user confirms**).
> Parent: `docs/remaining-work-plan.md` (build sequence S4/S5/S2/S6 + S1 E2E harness).
> Baseline verified 2026-10-27: Phases 0,1,2,3,6 at 100%; Phase 4 needs only E2E; Phase 5 needs
> Agno/approval/voice; backend pytest **337 passed**; `npm run typecheck` + `npm run build` green.
>
> Conventions every item below must follow (verified in-tree):
> FastAPI routers in `backend/app/api/routers/*.py` registered in `routers/__init__.py`;
> services in `backend/app/services/<domain>/`; SQLAlchemy models auto-upgraded by `init_db`;
> tests use `TestClient` + `/api/auth/register` fixture pattern; frontend uses `api` from `@/lib/api`
> (paths WITHOUT `/api` prefix) or axios `api-client` (paths WITH `/api` prefix), React Query v5,
> shadcn-style `components/ui/*`, `SymbolSearch`, amber classes for warnings (no `warning` theme color).
> **Hard rules**: no fabricated market data (degrade honestly with null/notes); paper-only defaults;
> live orders always go through the orders service + Action Center approval when semi-auto is on.

---

## Phase 7 — Flow Visual Strategy Builder (effort XL)

### 7.1 Goal
Drag-and-drop strategies (market data → indicators → conditions → orders/notifications) that validate,
dry-run, and execute on a schedule — reusing StockOS market data, indicator functions
(`tests/test_indicators.py`), the orders service, and the existing scheduled-runs service.

### 7.2 Backend design (`backend/app/services/flow/`, router `backend/app/api/routers/flow.py`)
- `schemas.py` — Pydantic graph model: `FlowNode(id, type, params)`, `FlowEdge(from, to)`,
  `FlowGraph(nodes[], edges[])`. Node types v1: `market_data`, `indicator`, `condition`,
  `order`, `notification`. Closed enum — unknown types rejected with 422.
- `validator.py` — pure function `validate(graph) -> list[Finding]`: unknown node types, dangling
  edges, cycles, missing required params (e.g. `order` without symbol/side/qty), live-order nodes
  without an approval-safe configuration. Unit-testable, no I/O.
- `store.py` + model `FlowGraph` table (`id, name, definition JSON, schedule_cron, enabled,
  paper_only=True, created_at, updated_at`).
- `executor.py` — `run(graph, mode="dry_run"|"live") -> RunReport(step_results[])`. Market data via
  existing OHLCV/Historify services; indicators via existing indicator functions; conditions as
  pure expression eval over a **whitelisted** operator set (no `eval` of user code — operator map only).
  `order` nodes call the orders service (paper broker default; live only if analyzer/live is enabled
  AND semi-auto approval routes through Action Center). `notification` nodes write to the Phase 9
  alert hook when present, else log.
- Scheduler wiring: register enabled graphs with the existing scheduled-runs service by cron;
  one runner honors `enabled` + `paper_only`.
- Router `flow.py`:

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/flow/graphs`, `/flow/graphs/{id}` (+PATCH/DELETE) | CRUD |
| POST | `/flow/validate` | dry validation, returns findings |
| POST | `/flow/run` | `{graph_id \| inline_graph, mode}` → RunReport |
| GET/POST | `/flow/import`, `/flow/export/{id}` | JSON backup/restore |

### 7.3 Frontend (`frontend/app/flow/*`, new dep `@xyflow/react`)
- `/flow` list page (table: name, enabled, schedule, last run) + `/flow/[id]` builder page:
  palette → canvas (`@xyflow/react`), property panel per node type, Validate button (findings list),
  Dry-run button (step results), enable/schedule toggle, import/export buttons.
- Nav entry under Trading group in `navigation.tsx`. React Query for graphs/runs; error-banner pattern.

### 7.4 Steps
1. `npm i @xyflow/react`; backend `services/flow/{__init__,schemas}.py` + node-type enum.
2. `validator.py` + `tests/test_flow.py` (validator cases: cycle, dangling, bad params).
3. `FlowGraph` model + store + CRUD routes + tests.
4. `executor.py` dry-run path (market data + indicators + conditions only) + tests with synthetic chains.
5. Live `order`/`notification` nodes wired to orders service + approval semantics + tests (paper only).
6. Scheduler registration + enable/disable routes.
7. Frontend list + builder pages; validate/dry-run UX; nav entry.
8. Import/export routes + UI buttons; typecheck + build; zero-console-error check.
9. Docs checkbox updates in this file's plan + study doc.

### 7.5 Risks
- Execution safety: live `order` nodes MUST NOT bypass approval — enforced in executor, covered by a
  dedicated test (semi-auto → Action Center item created, no direct fill).
- Scope creep (loops, variables, backtesting parity): v1 is DAG-only, no loops; defer.

---

## Phase 8 — Python Strategy Host (effort L)

### 8.1 Goal
User-written Python strategies that run **out-of-process** (never `exec` in the server), on a schedule,
with encrypted env vars and live logs. **Paper-only in v1**; live use stays behind analyzer + approval.

### 8.2 Backend design (`backend/app/services/strategy_host/`, router `strategy_host.py`)
- `store.py` + model `StrategyScript(id, name, code, schedule_cron, enabled, created/updated)`.
- `runner.py` — `multiprocessing` (spawn) worker: runs script with a minimal `ctx` object
  (`ctx.history(symbol, interval, period)`, `ctx.place_order(...)` → orders service on paper broker,
  `ctx.log(...)`), hard timeout + kill, per-run working dir, stdout/stderr capture ring buffer.
  No broker secrets injected; user secrets come only from per-script encrypted env (Fernet helpers in
  `core/security.py`, same pattern as stored credentials).
- Scheduler wiring: same pattern as Phase 7 (cron → runner).
- Router:

| Method | Path | Purpose |
|---|---|---|
| GET/POST/PATCH/DELETE | `/strategy-host/scripts...` | CRUD |
| POST | `/strategy-host/scripts/{id}/run`, `/stop` | manual run / kill |
| GET | `/strategy-host/scripts/{id}/logs?tail=` | captured logs |
| GET/PUT | `/strategy-host/scripts/{id}/env` | encrypted env vars (values never echoed back) |

### 8.3 Frontend (`frontend/app/strategies/*`, new dep `@uiw/react-codemirror`)
- Scripts list + editor page (CodeMirror, python mode), Run/Stop, schedule field, env-var editor
  (write-only values), log viewer (polling every 2–5 s; no new socket infra in v1).

### 8.4 Steps
1. Store + model + CRUD routes + tests.
2. Runner (spawn, timeout/kill, `ctx` surface paper-only) + unit tests with trivial scripts
   (fast-first, no-data, timeout-kill cases).
3. Env encryption endpoints + tests (round-trip; values never readable via GET).
4. Log capture + `/logs` + tests.
5. Scheduler wiring + enable/disable.
6. Frontend pages + nav entry; typecheck + build.
7. Docs updates.

### 8.5 Risks
- Process abuse (infinite loops, disk/CPU): timeout + kill + working-dir confinement are mandatory,
  with tests proving the kill path.
- Secret leakage into logs: `ctx` redacts values matching stored env names (test with canary value).

---

## Phase 9 — Monitoring, Notifications, Market Calendar, Broker Admin (effort M/L)

### 9.0 Build order inside Phase 9
9a monitoring → 9d calendar → 9b PnL → 9c Telegram → 9e broker admin. (Each shippable alone.)

### 9a. Monitoring middleware + dashboards
- `core/metrics.py`: `MetricsMiddleware` records per-route latency/count/5xx into a small SQLite table
  (`request_metrics`: ts, route, ms, status) with retention prune (e.g. 7 days, background task).
- `services/health_metrics.py`: extends existing health endpoints with process stats —
  new dep `psutil` (FD count, RSS, threads) + DB file sizes + scheduler heartbeat.
- Router `monitoring.py`: `GET /monitoring/latency?window=`, `/monitoring/traffic`, `/monitoring/health`.
- Frontend `frontend/app/monitoring/*`: latency chart + traffic table + health cards
  (reuse `lightweight-charts`, already a dep). Tests: middleware records; prune works.

### 9b. PnL tracker
- `services/pnl.py`: realized/unrealized + equity curve from paper-broker orders/positions
  (existing data — no new capture needed in v1).
- Router: `GET /pnl/summary`, `GET /pnl/equity?range=`.
- Frontend `frontend/app/pnl/*`: summary cards + equity curve (`lightweight-charts`).

### 9c. Telegram alerts (WhatsApp explicitly out of scope — Tier 3)
- New dep `python-telegram-bot`. `services/telegram/{bot.py, alerts.py, config.py}`:
  long-polling worker (background thread, start/stop with app lifespan), **read-only commands v1**
  (`/status`, `/positions`, `/pnl`) — approvals stay in the web UI deliberately.
- Alert hooks: order filled/rejected, kill-switch, daily-loss guard — via a tiny `alerts.emit(event)`
  helper that is a no-op when unconfigured.
- Bot token stored encrypted (Fernet) via settings; config UI card on settings page
  (token write-only, chat-id allowlist, test-message button). Tests: emit-noop, command handlers
  with fake update objects, token never returned by API.

### 9d. Market calendar + timings admin
- `services/market_calendar.py` + seed file `backend/app/data/nse_holidays.json` (maintained by hand;
  documented limitation — no guaranteed free holiday API) + `MarketHoliday` table for admin CRUD.
- Router `calendar.py`: `GET /calendar/holidays`, `GET /calendar/timings`, `GET /calendar/status`
  (open/closed now, lunch/session logic reusing `services/market_session.py`).
- Frontend `frontend/app/calendar/*` admin page (holiday table + add/remove, timings form).

### 9e. Broker TOTP/auth flows + admin diagnostics
- Router additions on `brokers.py`: `GET /brokers/diagnostics` (per configured broker: plugin present,
  credentials stored Y/N — never values, last auth result, supported exchanges/capabilities),
  `POST /brokers/{name}/auth/verify` (credential check without trading), `PUT /brokers/{name}/totp-seed`
  (TOTP seed write-only, Fernet-encrypted, admin-only route guard by role).
- Frontend: broker-management page gains a Diagnostics card + TOTP-seed dialog (write-only).
- Tests: diagnostics shape, seed never readable, non-admin 403.

---

## Phase 10 — Polish and Hardening (effort M)

1. **E2E suite** (extends the S1 Playwright harness): auth+TOTP, order→approval→execute,
   historify job lifecycle, options-analytics render, flow dry-run, strategy-host run+logs.
   Gate: all green on a fresh local DB.
2. **Performance pass**: Historify bulk-ingest timing + DuckDB query timing recorded as baselines in
   `docs/engineering/`; frontend `next build` size sanity (no new heavy deps without approval).
3. **Security review**: OWASP checklist (auth, CSRF, rate limits, CSP headers live-verified),
   secrets audit (`git grep` for tokens/keys — must be empty), `pip`/`npm` audit triage.
4. **Docs + demo**: README touch-up, phase checkboxes final pass, fresh demo media via local-only
   `demo.mjs` (never committed), front-page GIF refresh.
5. **Release checklist** for merging `StockAlgo_1` → `main`: full pytest + typecheck + build green,
   zero console errors on touched pages, CHANGELOG-style summary in the merge description.

---

## Cross-phase dependency map

```
S1 e2e harness ──► Phase 4 E2E (E-1) ──► regression net for everything below
9a monitoring ──► 9b/9c/9d/9e (independent services, shared router/frontend patterns)
Phase 9 alerts hook ◄── Phase 7/8 notification nodes (emit() is a no-op until 9c lands — safe order)
Phase 5 Agno (flagged) ──► optional Flow/strategy-host agent nodes (deferred, not in v1 scope)
Phase 10 ──► needs S1 harness + all features merged to StockAlgo_1 first
```

## Effort roll-up (calendar, 1 dev, serial)

| Item | Effort |
|---|---|
| S1 E2E harness + E-1 | S/M (3–5 days) |
| 9a monitoring | S/M (3–4 days) |
| 9d calendar | S (2–3 days) |
| 9b PnL | S (2–3 days) |
| 9c Telegram | M (4–6 days) |
| 9e broker admin | S/M (3–4 days) |
| Phase 5 remainder (P5-b,a,c) | M/L (2–3 weeks) |
| Phase 7 Flow | XL (4–6 weeks) |
| Phase 8 strategy host | L (3–4 weeks) |
| Phase 10 polish | M (2 weeks) |
