# Phase 8 — Python Strategy Host: Concrete Implementation Tasks

Branch: `StockAlgo_1`

Design reference: `docs/phase7-10-detailed-plan.md` (section 8).

## Scope for this iteration
User-written Python strategies running out-of-process (never `exec` in the server), on a schedule,
with encrypted env vars and live logs. Paper-only in v1; live use stays behind analyzer + approval.

## Not completed (remaining)
- [ ] Add `@uiw/react-codemirror` npm dependency for the editor page (verified absent).
- [ ] Add `StrategyScript` model (`id, name, code, schedule_cron, enabled, timestamps`) + store
      (`backend/app/services/strategy_host/store.py`) + CRUD routes.
- [ ] Add runner (`backend/app/services/strategy_host/runner.py`): `multiprocessing` (spawn)
      worker with a minimal `ctx` object (`ctx.history(symbol, interval, period)`,
      `ctx.place_order(...)` -> orders service on the paper broker only, `ctx.log(...)`), hard
      timeout + kill, per-run working dir, stdout/stderr capture ring buffer. No broker secrets
      injected into scripts.
- [ ] Add encrypted per-script env (`GET/PUT /strategy-host/scripts/{id}/env`) using the Fernet
      helpers in `core/security.py` — values are write-only, never echoed back by GET.
- [ ] Add log capture + `GET /strategy-host/scripts/{id}/logs?tail=`.
- [ ] Add manual `POST /strategy-host/scripts/{id}/run|stop` + scheduler wiring for enabled scripts.
- [ ] Add router + registration in `routers/__init__.py`.
- [ ] Add `backend/tests/test_strategy_host.py`: trivial-script run, fast-fail (no data),
      timeout-kill proof, env round-trip (values never readable), log redaction with a canary value.
- [ ] Add frontend `frontend/app/strategies/*`: scripts list + editor page (CodeMirror, python),
      Run/Stop, schedule field, write-only env editor, log viewer (2–5 s polling, no new socket
      infra in v1). Nav entry.
- [ ] Run `npm run typecheck` + `npm run build`; zero-console-error check.

## Files touched (planned)
- `backend/app/services/strategy_host/{__init__,store,runner}.py`
- `backend/app/db/models/` (`StrategyScript`)
- `backend/app/api/routers/strategy_host.py`
- `backend/app/api/routers/__init__.py`
- `backend/tests/test_strategy_host.py`
- `frontend/app/strategies/*`
- `frontend/components/navigation.tsx`
- `frontend/package.json` (`@uiw/react-codemirror`)
