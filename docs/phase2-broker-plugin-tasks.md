# Phase 2 — Broker Plugin Contract: Concrete Implementation Tasks

Branch: `feature/openalgo-adaptation` (local only)

## Completed
- [x] Add `app/brokers/plugins/<name>/plugin.json` for paper, zerodha, angelone.
- [x] Add `app/brokers/plugin_loader.py` (lazy metadata loading, class loading, capability checks).
- [x] Add `/api/brokers/plugins` and capability endpoints.
- [x] Add `MasterContract` model and `/api/master-contract` CRUD/search routes.
- [x] All 261 backend tests pass.

## Next
- [ ] Refactor existing flat adapters into `app/brokers/<name>/` packages without breaking imports.
- [ ] Add plugin-based broker factory in order routing.
- [ ] Add master contract sync/import jobs.
- [ ] Add plugin loading tests.
