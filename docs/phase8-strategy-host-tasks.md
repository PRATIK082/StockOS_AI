# Phase 8 — Python Strategy Host: Concrete Implementation Tasks

Branch: `StockAlgo_1`

Design reference: `docs/phase7-10-detailed-plan.md` (section 8).

## Scope for this iteration
User-written Python strategies running out-of-process (never `exec` in the server), on a schedule,
with encrypted env vars and live logs. Paper-only in v1; live use stays behind analyzer + approval.

## Completed (commit 362640f, branch feature/flow-strategy-suite)
- [x] Add `@uiw/react-codemirror` npm dependency for the editor page (verified absent).
- [x] Add `StrategyScript` model (`id, name, code, schedule_cron, enabled, timestamps`) + store
      (`backend/app/services/strategy_host/store.py`) + CRUD routes.
- [x] Add runner (`backend/app/services/strategy_host/runner.py`): `multiprocessing` (spawn)
      worker with a minimal `ctx` object (`ctx.history(symbol, interval, period)`,
      `ctx.place_order(...)` -> orders service on the paper broker only, `ctx.log(...)`), hard
      timeout + kill, per-run working dir, stdout/stderr capture ring buffer. No broker secrets
      injected into scripts.
- [x] Add encrypted per-script env (`GET/PUT /strategy-host/scripts/{id}/env`) using the Fernet
      helpers in `core/security.py` — values are write-only, never echoed back by GET.
- [x] Add log capture + `GET /strategy-host/scripts/{id}/logs?tail=`.
- [x] Add manual `POST /strategy-host/scripts/{id}/run|stop` + scheduler wiring for enabled scripts.
- [x] Add router + registration in `routers/__init__.py`.
- [x] Add `backend/tests/test_strategy_host.py`: trivial-script run, fast-fail (no data),
      timeout-kill proof, env round-trip (values never readable), log redaction with a canary value.
- [x] Add frontend `frontend/app/strategies/*`: scripts list + editor page (CodeMirror, python),
      Run/Stop, schedule field, write-only env editor, log viewer (2–5 s polling, no new socket
      infra in v1). Nav entry.
- [x] Run `npm run typecheck` + `npm run build`; zero-console-error check.

### Deviations from the plan (all verified)
- `@codemirror/lang-python` also installed (real Python highlighting; the builder's
  StreamLanguage fallback was replaced by the parent).
- Env PUT accepts a flat merge dict (`{"KEY": "value"}`, `None` deletes); GET returns
  key names only.
- `POST /run` accepts an empty body or `{timeout_seconds: 1-600}`; single-flight per
  script (409 when a run is active); `/stop` is 404 when the script never ran, 200 with
  `{stopped: false}` when idempotent.
- Child processes `exec` user code (server process never does); intents are filed by the
  parent (approval mode files pending Action Center items, else paper fills).
- Tests use a `STRATEGY_HOST_HISTORY_STUB_JSON` env hook (test-only) because children
  cannot inherit monkeypatches.
- Strategy E2E: `frontend/e2e/flow-strategy.spec.ts` (run-to-completion + logs,
  timeout-kill, env write-only, `/strategies` page lists the API-created script).

## Files touched (planned)
- `backend/app/services/strategy_host/{__init__,store,runner}.py`
- `backend/app/db/models/` (`StrategyScript`)
- `backend/app/api/routers/strategy_host.py`
- `backend/app/api/routers/__init__.py`
- `backend/tests/test_strategy_host.py`
- `frontend/app/strategies/*`
- `frontend/components/navigation.tsx`
- `frontend/package.json` (`@uiw/react-codemirror`)
