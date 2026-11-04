# Remaining Work Plan — StockAlgo_1 (audit + build sequence)

> Audit date: 2026-10-27. Branch: `StockAlgo_1` (local; **no push until the user confirms**).
> Method: every checkbox in `docs/phase*-tasks.md` + `docs/reference-platform-study-and-implementation-plan.md`
> verified against tracked files (routers, services, pages, tests, deps). Full pytest suite re-run
> during the audit: **337 passed** (plus `npm run typecheck` + `npm run build` green).
> Detailed design for Phases 7–10: `docs/phase7-10-detailed-plan.md`.

## 1. Verdict by phase

| Phase | Doc checkboxes before audit | Verified reality | Gaps |
|---|---|---|---|
| 0 Preparation | done | ✅ done | none |
| 1 Security/Auth | 5 boxes open | ✅ **100% done** — boxes were stale, now ticked (this audit) | none (see N1) |
| 2 Broker plugins | done | ✅ done (packages, factory, master-contract CRUD/sync/import) | none |
| 3 Historify | 1 box open | ✅ done (30+ endpoints + page) — box was stale | none |
| 4 Analyzer/Action Center | 2 boxes open | ✅ backend + UI done; ❌ E2E tests missing | E-1 |
| 5 AI agent | 3 boxes open | ✅ MCP client, chart markup, registries + pages; ❌ Agno migration, agent-tool approval, voice/attachments | P5-a/b/c |
| 6 Options suite | done | ✅ done (9 endpoints, margin, synthetic, page, tests) | none |
| 7 Flow builder | done | ✅ done (validator, executor, scheduler bridge, pages, E2E) — commit 362640f | none |
| 8 Strategy host | done | ✅ done (spawn runner, env encryption, logs, pages, E2E) — commit 362640f | none |
| 9 Monitoring/notify | open | ❌ ~0% (only analyzer square-off times exist) | F-9 |
| 10 Polish | open | 🟡 **partial (F-10 in progress)** — E2E harness exists (S1) and now covers flow dry-run + strategy-host run/logs (16/16 green); perf baselines, OWASP review, docs/demo refresh still open | F-10 |

- N1: Phase 1 "broker token revocation" = auth-token revocation (jti blacklist + `POST /auth/logout`
  + 30-min JWT exp) is done. Per-broker credential rotation UI is folded into F-9 admin diagnostics.
- Stale boxes fixed in this audit (docs only, uncommitted): phase1 ×5, phase3 ×1, phase4 ×1.

## 2. Genuine gap list (what is NOT done)

- **E-1** (Phase 4 tail): E2E tests for approval-gated routing. No `e2e/` dir, no Playwright config.
- **P5-a**: Agno + LiteLLM runtime migration (must be feature-flagged, old runtime stays default).
- **P5-b**: agent-tool-specific order approval (generic Action Center queue exists).
- **P5-c**: voice / attachments / web-search / skills in agent runtime.
- **F-7** (Phase 7): Flow builder — ✅ DONE (commit 362640f + E2E in `flow-strategy.spec.ts`).
- **F-8** (Phase 8): Python strategy host — ✅ DONE (commit 362640f + E2E in `flow-strategy.spec.ts`).
- **F-9** (Phase 9): latency/traffic/health middleware + dashboards; PnL tracker page; Telegram bot + UI;
  market calendar/holidays/timings admin; broker TOTP/auth flows + admin diagnostics.
- **F-10** (Phase 10): E2E suite EXISTS (16 tests: 3 auth + 1 approval + 4 streaming + 8 flow-strategy, all green);
  remaining polish = perf pass, security review, docs + demo refresh.

## 3. Build sequence (proposed start plan)

### S1 — E2E harness + close Phase 4 (E-1) — effort S/M — START HERE
- Add `@playwright/test` (dev dep) + browsers (local-only, gitignored artifacts), `e2e/` smoke:
  login → 2FA → approval queue approve→execute on the paper broker.
- Closes Phase 4 to 100% and gives a regression net for S2–S5.

### S2 — Phase 9 ops foundation (F-9) — DONE (backend 06c77a2; frontend+nav af9d511)
1. Latency/traffic middleware + health metrics collector + `frontend/app/operations/page.tsx` (tables/tiles, no new chart dep).
2. Market calendar service (holidays/timings) + `frontend/app/calendar/page.tsx`; broker TOTP/auth flows + diagnostics card on broker-management page.
3. PnL tracker `frontend/app/pnl/page.tsx` (inline SVG equity curve, no new chart dep).
4. Telegram bot service + settings-page config card (`python-telegram-bot` added).

### S3 — Phase 5 remainder (P5-b → P5-a → P5-c) — DONE (74a9b94, d9cfaae, 58e113a)
- P5-b agent-tool approval registry + autopilot approval routing; P5-a Agno+LiteLLM runtime
  (env-flagged, legacy default); P5-c voice STT / attachments / web-search / skills + agent-extras page.

### S3.5 — Live-quote streaming (unplanned addition, DONE — commit pending)
- `services/streaming/hub.py` poll hub + `routers/streaming.py` (REST status/latest/market,
  WS /quotes + /market, accept-then-close 4401); `frontend/app/streaming/page.tsx` + nav;
  `tests/test_streaming.py` (8) + `e2e/streaming.spec.ts` (4, E2E suite now 8/8 green).
- Also fixed systemic test rot: instance-level `monkeypatch.setattr(market_data_singleton, …)`
  leaves a permanent `__dict__` shadow after teardown — converted all such patches to
  class-level `MarketDataService` patches in 10 test files.

### S3 — Phase 5 remainder (P5-b → P5-a → P5-c) — effort L
- P5-b first (small, high safety value), then flagged Agno/LiteLLM migration, then P5-c extras.

### S4 — Phase 7 Flow builder (F-7) — DONE (commit 362640f)
- New dep `@xyflow/react`; backend `services/flow/` (validator, executor, scheduler wiring);
  `frontend/app/flow/*`.
- E2E (F-10 slice): `frontend/e2e/flow-strategy.spec.ts` — CRUD, validate (422 unknown-type /
  dangling-edge findings), dry-run, POST-only `/flow/import` + `/flow/export/{id}`
  round-trip, `/flow` UI listing. Suite 16/16 green.

### S5 — Phase 8 strategy host (F-8) — DONE (commit 362640f)
- `services/strategy_host/` process runner + scheduler; editor page (`@uiw/react-codemirror`);
  encrypted env vars; log streaming.
- E2E (F-10 slice): trivial run → completed + log text, `timeout_seconds` kill,
  409 single-flight on concurrent run, env PUT/GET names-only, `/strategies` UI
  listing. Suite 16/16 green.

### S6 — Phase 10 polish (F-10) — effort M (E2E slice DONE, rest open)
- Full E2E suite ✅ (flow + strategy-host slice: 8 tests, 16/16 green) — perf pass,
  OWASP/security review (secrets audit: empty, 2026-11-05), docs + demo refresh still open.
- Contract deviations recorded in `docs/phase7-10-detailed-plan.md`: POST-only
  `/flow/import`; strategy run 409 single-flight; logs Clear is view-only.

## 4. Dependencies to add (all currently absent)

`agno`, `litellm`, `python-telegram-bot`, `@xyflow/react`, `@uiw/react-codemirror`, `@playwright/test`.
(Plotly deliberately deferred earlier — revisit in S2/S4 only if tables prove insufficient.)

## 5. Definition of done per item

Backend routes + tests, frontend page wired to real endpoints (no fabricated data),
`npm run typecheck` + `npm run build` green, pytest green, zero console errors on touched pages.
