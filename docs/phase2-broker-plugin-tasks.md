# Phase 2 — Broker Plugin Contract: Concrete Implementation Tasks

Branch: `StockAlgo_1`

## Completed
- [x] Add `app/brokers/plugins/<name>/plugin.json` for paper, zerodha, angelone.
- [x] Add `app/brokers/plugin_loader.py` (lazy metadata loading, class loading, capability checks).
- [x] Add `/api/brokers/plugins` and capability endpoints.
- [x] Add `MasterContract` model and `/api/master-contract` CRUD/search routes.
- [x] All 261 backend tests pass.

## Next
- [x] Refactor existing flat adapters into `app/brokers/<name>/` packages without breaking imports.
- [x] Add plugin-based broker factory in order routing.
- [x] Add master contract sync/import jobs.
- [x] Add plugin loading tests.
