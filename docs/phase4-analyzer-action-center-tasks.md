# Phase 4 — Analyzer Mode + Action Center: Concrete Implementation Tasks

Branch: `feature/openalgo-adaptation` (local only)

## Completed
- [x] Add `ActionCenterItem` model.
- [x] Add approval queue routes: list, approve, reject, execute.
- [x] Add semi-auto order routing when `REQUIRE_APPROVAL`.
- [x] Add tests covering action center flow.

## Not completed (remaining)
- [ ] Analyzer Mode sandbox capital/margin/risk limits.
- [ ] Square-off and session reset schedules.
- [ ] Smart order (best price, chase).
- [ ] Basket orders.
- [ ] Split orders.
- [ ] Frontend approval UX and analyzer controls.
- [ ] End-to-end tests for approval-gated live routing.
