# Phase 3 — Historify: Concrete Implementation Tasks

Branch: `feature/openalgo-adaptation` (local only)

## Completed
- [x] Add DuckDB OHLCV warehouse service (`app/services/historify/store.py`).
- [x] Add ingest, query, and status routes (`app/api/routers/historify.py`).
- [x] Register router in `app/api/routers/__init__.py`.
- [x] Add `tests/test_historify.py`.
- [x] All backend tests pass (261).

## Not completed (remaining)
- [x] Watchlist CRUD and per-symbol catalog (backend).
- [x] Download jobs with pause/resume/cancel (backend).
- [x] Incremental updates and gap detection (backend).
- [x] Import/export flows (backend).
- [x] FNO discovery and contract handling (backend).
- [ ] Frontend Historify pages and controls.
- [x] Auth-gated integration tests beyond ingest/query/status (backend).
