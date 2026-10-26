# Phase 4 — Analyzer Mode + Action Center: Concrete Implementation Tasks

Branch: `feature/openalgo-adaptation` (local only)

## Completed
- [x] Add `ActionCenterItem` model.
- [x] Add approval queue routes: list, approve, reject, execute.
- [x] Add semi-auto order routing when `REQUIRE_APPROVAL`.
- [x] Add tests covering action center flow.

## Completed (this change)
- [x] Analyzer Mode sandbox capital/margin/risk limits.
- [x] Square-off and session reset schedules (config).
- [x] Smart order (best price, chase).
- [x] Basket orders.
- [x] Split orders.
- [x] Action center integration for approval of these orders.
- [x] Backend tests for analyzer + smart/basket/split + approval flow.

## Not completed (remaining)
- [ ] Frontend approval UX and analyzer controls.
- [ ] End-to-end tests for approval-gated live routing.
