# Phase 6 — Options Suite: Concrete Implementation Tasks

Branch: `StockAlgo_1`

## Scope for this iteration
Options analytics over real provider chains plus a transparent margin calculator — no fabricated
data, no new npm dependency (the Plotly idea was skipped on purpose).

## Completed
- [x] Options analytics service (`app/services/options/analytics.py`): max pain, OI profile,
      OI change, IV smile + 25-delta skew, volatility surface + ATM term structure, gamma
      exposure (zero-gamma / flip strike), straddle payoff with breakevens.
- [x] Margin calculator + synthetic futures (`app/services/options/margin.py`) with a
      transparent leverage table; every response is flagged `is_estimate: true`.
- [x] Routers (`app/api/routers/options_analytics.py`): `/api/options/analytics/*`
      (max-pain, oi-profile, oi-change, iv-smile, vol-surface, gex, straddle) and
      `/api/options/margin/*` (calculate, synthetic-futures).
- [x] Router registration in `app/api/routers/__init__.py`.
- [x] Frontend page `frontend/app/options-analytics/page.tsx` (table-based) + nav entry
      under the Analytics group in `frontend/components/navigation.tsx`.
- [x] Tests: `backend/tests/test_options_phase6.py` (34 tests, all passing).

## Known behaviour (honest degradation, not bugs)
- The free TradingView options scanner publishes no open interest, so max pain, OI profile
  and GEX legitimately return empty values for those chains.
- A chain expiring today (0DTE) has no time value, so the 25-delta skew is reported as
  unavailable instead of being filled with a proxy number.
- When a chain carries no OI, support/resistance and zero-gamma/flip levels are returned as
  null (not the first strike of the grid) with an explanatory note.
- When a chain publishes no option premium, the straddle endpoint returns `has_premium: false`,
  an empty breakeven list and null max profit/loss; only the expiry intrinsic curve is shown.
  The synthetic-futures endpoint adds a note that it was costed at zero premium.

## Files touched
- `backend/app/services/options/analytics.py`
- `backend/app/services/options/margin.py`
- `backend/app/api/routers/options_analytics.py`
- `backend/app/api/routers/__init__.py`
- `backend/tests/test_options_phase6.py`
- `frontend/app/options-analytics/page.tsx`
- `frontend/components/navigation.tsx`
