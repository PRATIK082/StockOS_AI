# Phase 3 — Historify: Concrete Implementation Tasks

Branch: `feature/openalgo-adaptation` (local only)

## Completed
- [x] Add DuckDB OHLCV warehouse service (`app/services/historify/store.py`).
- [x] Add ingest, query, and status routes (`app/api/routers/historify.py`).
- [x] Register router in `app/api/routers/__init__.py`.
- [x] Add `tests/test_historify.py`.
- [x] All backend tests pass (261).

## Not completed (remaining)
- [ ] Watchlist CRUD and per-symbol catalog.
- [ ] Download jobs with pause/resume/cancel.
- [ ] Incremental updates and gap detection.
- [ ] Import/export flows.
- [ ] FNO discovery and contract handling.
- [ ] Frontend Historify pages and controls.
- [ ] Auth-gated integration tests beyond ingest/query/status.
