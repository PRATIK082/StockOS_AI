# Phase 10 — Polish and Hardening: Concrete Implementation Tasks

Branch: `StockAlgo_1`

Design reference: `docs/phase7-10-detailed-plan.md` (section 10).

## Scope for this iteration
Release gate for merging `StockAlgo_1` -> `main`: E2E proof, performance baselines, security
review, docs + demo refresh. Starts only after the S1 Playwright harness exists and all
features are merged to this branch.

## Not completed (remaining)
- [ ] E2E suite (extends the S1 harness, new dep `@playwright/test` — verified absent):
      auth+TOTP login, order -> approval -> execute, Historify job lifecycle, options-analytics
      page render, Flow dry-run, strategy-host run+logs. Gate: all green on a fresh local DB.
      (Also closes Phase 4 item E-1: approval-gated live routing E2E.)
- [ ] Performance pass: record Historify bulk-ingest timing + DuckDB query timing baselines in
      `docs/engineering/`; frontend `next build` bundle-size sanity (no new heavy deps without
      approval).
- [ ] Security review: OWASP checklist (auth, CSRF, rate limits, CSP headers live-verified),
      secrets audit (`git grep` for tokens/keys — must be empty), `pip`/`npm` audit triage.
- [ ] Docs + demo: README touch-up, final checkbox pass over all `docs/phase*-tasks.md` files,
      fresh demo media via local-only `demo.mjs` (never committed), front-page GIF refresh.
- [ ] Release checklist for the `StockAlgo_1` -> `main` merge: full pytest + typecheck + build
      green, zero console errors on touched pages, CHANGELOG-style summary in the merge
      description. Merge itself only after user confirmation (no-push rule still applies).

## Files touched (planned)
- `frontend/tests/e2e/*` (or wherever the S1 harness lives)
- `docs/engineering/` (perf baselines)
- `README.md`
- `docs/phase*-tasks.md` (checkbox final pass)
- `demo.gif`, `demo.mp4` (regenerated, committed as before)
