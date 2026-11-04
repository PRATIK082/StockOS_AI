# Phase 7 — Flow Visual Strategy Builder: Concrete Implementation Tasks

Branch: `StockAlgo_1`

Design reference: `docs/phase7-10-detailed-plan.md` (section 7).

## Scope for this iteration
Drag-and-drop strategies (market data -> indicators -> conditions -> orders/notifications) that
validate, dry-run, and execute on a schedule. DAG-only in v1 (no loops). Reuses StockOS market
data, the indicator functions covered by `tests/test_indicators.py`, the orders service, and the
existing scheduled-runs service.

## Completed (commit 362640f, branch feature/flow-strategy-suite)
- [x] Add `@xyflow/react` npm dependency (none of the Flow deps exist yet — verified).
- [x] Add graph schemas (`backend/app/services/flow/schemas.py`): `FlowNode` (closed type enum:
      `market_data`, `indicator`, `condition`, `order`, `notification`), `FlowEdge`, `FlowGraph`.
      Unknown node types rejected with 422.
- [x] Add pure validator (`backend/app/services/flow/validator.py`): unknown types, dangling
      edges, cycles, missing required params (e.g. `order` without symbol/side/qty), live-order
      nodes without approval-safe config. No I/O, unit-testable.
- [x] Add `FlowGraph` model (`id, name, definition JSON, schedule_cron, enabled,
      paper_only=True, timestamps`) + store + CRUD routes (`GET/POST/PATCH/DELETE
      /flow/graphs...`).
- [x] Add executor (`backend/app/services/flow/executor.py`): `run(graph,
      mode="dry_run"|"live") -> RunReport`. Market data via existing OHLCV/Historify services;
      indicators via existing indicator functions; conditions via a whitelisted operator map
      (no `eval` of user input). `order` nodes call the orders service (paper default; live only
      through analyzer + Action Center approval). `notification` nodes call the Phase 9 alert
      hook when present, else log.
- [x] Wire enabled graphs into the existing scheduled-runs service by cron; runner honors
      `enabled` + `paper_only`.
- [x] Add router `backend/app/api/routers/flow.py` + registration in `routers/__init__.py`:
      CRUD, `POST /flow/validate`, `POST /flow/run`, `GET/POST /flow/import|export`.
- [x] Add `backend/tests/test_flow.py`: validator cases (cycle, dangling, bad params),
      dry-run with synthetic chains, live-order-in-semi-auto test (Action Center item created,
      no direct fill).
- [x] Add frontend `frontend/app/flow/*`: list page (name, enabled, schedule, last run) +
      builder page (palette, canvas, property panel, Validate, Dry-run, enable/schedule toggle,
      import/export). Nav entry under the Trading group.
- [x] Run `npm run typecheck` + `npm run build`; zero-console-error check on both pages.

### Deviations from the plan (all verified)
- `POST /flow/import` (plan said GET): import takes a JSON body, so POST is correct.
- `FlowNode.type` is a plain `str` (not a Literal enum) so the pure validator can report
  unknown types as findings; the router rejects them at the boundary with 422.
- Flow E2E: `frontend/e2e/flow-strategy.spec.ts` (create/get/validate/dry-run,
  import/export round-trip, `/flow` page lists the API-created graph).

## Files touched (planned)
- `backend/app/services/flow/{__init__,schemas,validator,executor,store}.py`
- `backend/app/db/models/` (`FlowGraph`)
- `backend/app/api/routers/flow.py`
- `backend/app/api/routers/__init__.py`
- `backend/tests/test_flow.py`
- `frontend/app/flow/*`
- `frontend/components/navigation.tsx`
- `frontend/package.json` (`@xyflow/react`)
