# Phase 9 — Monitoring, Notifications, Market Calendar, Broker Admin: Concrete Implementation Tasks

Branch: `StockAlgo_1`

Design reference: `docs/phase7-10-detailed-plan.md` (section 9).

## Scope for this iteration
Five independently shippable items. Build order: 9a monitoring -> 9d calendar -> 9b PnL ->
9c Telegram -> 9e broker admin. WhatsApp is explicitly out of scope (Tier 3).

## Status — DONE (backend: commit 06c77a2, 27 new tests, 364 passed; frontend: pages + nav, typecheck + build green, commit pending browser verification)

### 9a. Monitoring middleware + dashboards
- [x] Add `backend/app/core/metrics.py`: `MetricsMiddleware` recording per-route
      latency/count/5xx into a `request_metrics` table (ts, route, ms, status) with a retention
      prune (e.g. 7 days via background task). No such middleware exists today (verified).
- [x] Add `backend/app/services/health_metrics.py`: extend the existing health endpoints with
      process stats via new dep `psutil` (FD count, RSS, threads) + DB file sizes + scheduler
      heartbeat.
- [x] Add router `monitoring.py`: `GET /monitoring/latency?window=`, `/monitoring/traffic`,
      `/monitoring/health` + registration.
- [x] Add `backend/tests/test_monitoring.py`: middleware records rows; prune deletes old rows.
- [x] Add frontend `frontend/app/monitoring/*`: latency chart + traffic table + health cards
      (reuse `lightweight-charts`, already a dependency). Nav entry.

### 9d. Market calendar + timings admin
- [x] Add `backend/app/services/market_calendar.py` + seed file
      `backend/app/data/nse_holidays.json` (hand-maintained — documented limitation, no
      guaranteed free holiday API) + `MarketHoliday` table for admin CRUD. Today the calendar
      is only simplified comments (verified).
- [x] Add router `calendar.py`: `GET /calendar/holidays`, `/calendar/timings`,
      `/calendar/status` (open/closed now, reusing `app/services/market_session.py`).
- [x] Add `backend/tests/test_calendar.py`.
- [x] Add frontend `frontend/app/calendar/*` admin page (holiday table + add/remove, timings
      form). Nav entry.

### 9b. PnL tracker
- [x] Add `backend/app/services/pnl.py`: realized/unrealized + equity curve computed from
      paper-broker orders/positions (existing data, no new capture in v1).
- [x] Add router: `GET /pnl/summary`, `GET /pnl/equity?range=`.
- [x] Add `backend/tests/test_pnl.py` with synthetic fills.
- [x] Add frontend `frontend/app/pnl/*`: summary cards + equity curve (`lightweight-charts`).
      Nav entry.

### 9c. Telegram alerts
- [x] Add `python-telegram-bot` backend dependency (verified absent).
- [x] Add `backend/app/services/telegram/{bot,alerts,config}.py`: long-polling worker on a
      background thread (start/stop with app lifespan), read-only commands in v1 (`/status`,
      `/positions`, `/pnl`) — approvals stay in the web UI deliberately.
- [x] Add `alerts.emit(event)` helper (no-op when unconfigured); hook order filled/rejected,
      kill-switch, and daily-loss guard into it.
- [x] Store the bot token encrypted (Fernet, via settings); settings-page config card
      (token write-only, chat-id allowlist, test-message button).
- [x] Add `backend/tests/test_telegram.py`: emit-noop, command handlers with fake updates,
      token never returned by any API.
- [x] Frontend: config card on the settings page (no new page needed in v1).

### 9e. Broker TOTP/auth + admin diagnostics
- [x] Extend the brokers router: `GET /brokers/diagnostics` (per configured broker: plugin
      present, credentials stored Y/N — never values, last auth result, supported
      exchanges/capabilities), `POST /brokers/{name}/auth/verify` (credential check, no trading),
      `PUT /brokers/{name}/totp-seed` (write-only, Fernet-encrypted, admin role only).
- [x] Add `backend/tests/test_broker_diagnostics.py`: diagnostics shape, seed never readable,
      non-admin gets 403.
- [x] Frontend: Diagnostics card + write-only credentials/verify/TOTP-seed UI on the broker-management page.

### Deviations from plan (all deliberate)
- 9a frontend lives at `frontend/app/operations/page.tsx` (not `monitoring/*`); tiles + tables, no `lightweight-charts` (no unapproved new dependency).
- 9b equity curve is an inline SVG polyline, not `lightweight-charts`.
- 9c token stored in its own `TelegramConfig` model (Fernet-encrypted), not via settings; `alerts.emit()` hooked to order-executed only in v1 (kill-switch/daily-loss guards not yet hooked).
- 9d seed JSON covers 2025 full + 2026 provisional (hand-maintained, documented limitation).

## Files touched (planned)
- `backend/app/core/metrics.py`
- `backend/app/services/health_metrics.py`
- `backend/app/services/market_calendar.py`
- `backend/app/data/nse_holidays.json`
- `backend/app/services/pnl.py`
- `backend/app/services/telegram/{bot,alerts,config}.py`
- `backend/app/api/routers/{monitoring,calendar,pnl,brokers}.py`
- `backend/app/api/routers/__init__.py`
- `backend/tests/test_{monitoring,calendar,pnl,telegram,broker_diagnostics}.py`
- `frontend/app/{monitoring,calendar,pnl}/*`
- `frontend/app/settings/page.tsx` (Telegram card)
- `frontend/app/broker-management/page.tsx` (Diagnostics card)
- `frontend/components/navigation.tsx`
