# StockOS AI backend — read-only performance audit (F10)

Scope: `backend/app` on branch `feature/flow-strategy-suite`. Read-only: no source edits, no git commands, no servers started. All `file:line` citations were verified by reading the files. No fixes implemented.

## (a) Endpoints that fan out to per-symbol provider calls in loops

1. `backend/app/api/routers/streaming.py:86` — `GET /streaming/quotes/latest` loops `wanted` sequentially with `await market_data.get_quote(sym)` per symbol. Severity: med. Recommendation: `asyncio.gather` with semaphore (e.g. 8, matching intraday/sectors) + honor `MAX_SYMBOLS_PER_CONN`.
2. `backend/app/api/routers/portfolio.py:27` — `GET /portfolio` loops holdings, one `market_data.get_quote(h.symbol)` each (`backend/app/api/routers/portfolio.py:31`). Severity: high. Recommendation: batch/gather with concurrency cap + short TTL cache; return partial failures as now but concurrently.
3. `backend/app/api/routers/terminal.py:75` — `GET /terminal/positions` loops `broker.positions()`, one `market_data.get_quote(symbol)` each (`backend/app/api/routers/terminal.py:80`). Severity: high. Same fix as (2). Helper `backend/app/api/routers/terminal.py:265` / `backend/app/api/routers/terminal.py:269` repeats the pattern in `_portfolio_summary`.
4. `backend/app/services/scanners/engine.py:75` — `MarketScanner.scan` does `asyncio.gather` over the whole universe with no semaphore; each symbol then costs up to 3 provider calls (`backend/app/services/scanners/engine.py:525`, `:529`, `:533`). Severity: high. Recommendation: bounded semaphore (8–16), keep per-scan `_cache`, consider `source=auto` history instead of fixed `provider="yahoo"`. Contrast `custom_scan` at `backend/app/services/scanners/engine.py:92`, which is fully sequential — same fix.
5. `backend/app/services/analysis/sectors.py:79` — sector analysis gathers over full universe but correctly caps with `asyncio.Semaphore(8)` (`backend/app/services/analysis/sectors.py:55`, `:60`). Severity: low (good pattern to copy). Recommendation: keep; add response caching (60s) since one `get_quote` per symbol is still a cold-start burst.
6. `backend/app/services/analysis/intraday.py:91` — intraday board gathers `symbols[:limit]` with `Semaphore(concurrency=8)` (`backend/app/services/analysis/intraday.py:66`, `:73`, `:79`). Severity: med. Recommendation: keep cap; default `limit=90` (`backend/app/api/routers/analysis.py:458`) × `get_history_auto` fallback chains (up to 4 providers, `backend/app/services/data/fallback.py:69`) is still up to ~360 provider calls worst case — lower default or cache board briefly.
7. `backend/app/services/deep/engine.py:79` — `DeepAnalysisEngine.stream` handles symbols strictly sequentially, each doing quote (`:84`), history (`:131`), options (`:174`), prediction (`:187`). `_resolve` is also sequential (`backend/app/services/deep/engine.py:214`, `:216`). Severity: high. Recommendation: gather per-symbol stages concurrently (cap 3–5 symbols, already capped at 5 in `:222`), or at least parallelize quote+history per symbol.
8. `backend/app/api/routers/quant.py:53` — `_fetch_panel` loops symbols sequentially with `get_history_auto` (`backend/app/api/routers/quant.py:55`). Severity: high. Recommendation: `asyncio.gather` + semaphore + cap on `len(symbols)` (currently unbounded client list).
9. `backend/app/services/autopilot/agents.py:229` — `signal_agent` loops `top` sequentially with `get_history_auto` per symbol (`:231`). `sentinel_agent` loops positions with `live_price` → `get_quote` (`:137`) plus 2 memory round-trips per position (`:142`, `:148`). `optionstrategy_agent` loops with `signals()` + `get_option_chain` per symbol (`:259`, `:268`). Severity: med. Recommendation: gather histories/quotes with cap; batch memory reads.
10. `backend/app/api/routers/options_analytics.py:125` / `:139` — `vol_surface` loops expiries sequentially (`max_expiries` 4–12, `:114`), each a live `get_option_chain`. Severity: med. Recommendation: gather expiries with cap 4 default; cache normalized chains briefly.
11. `backend/app/api/routers/analysis.py:488` / `:526` — `options/coverage` slices `by_market(market)[:limit]` then `asyncio.gather` probes — good, but `limit` up to 60 (`:475`) × live chain each. Severity: low. Keep cap.
12. `backend/app/api/routers/analysis.py:390` — `technical/{symbol}` falls back over 2 candidates sequentially after the first miss. Severity: low. Fine, but note it doubles latency on bare-ticker misses; prefer the service-level `_resolve_bare_history` (`backend/app/services/data/service.py:273`).
13. `backend/app/api/routers/trading.py:380` — `_resolve_simulate_price` tries up to 3 quote candidates sequentially. Severity: low. Acceptable (≤3 calls, rare path).
14. `backend/app/services/data/fallback.py:69` — `fetch_with_chain` walks providers sequentially until first non-empty (`:75` sanitizes + builds DataFrame per attempt). Severity: med. Recommendation: keep sequential (correct for fallback), but log/measure chain length; `get_history_auto` bare-ticker path can then try 3 more candidates × full chains (`backend/app/services/data/service.py:286`) — cap total attempts.

## (b) Unbounded list/query endpoints (missing pagination/limits)

1. `backend/app/api/routers/orders.py:289` — `GET /v1/orders` loads all user orders (`.all()` at `:297`), no limit. Severity: high. Recommendation: `limit`/`offset` (default 50–100, max 500) + `order_by created_at desc` already present (`:295`).
2. `backend/app/api/routers/action_center.py:22` — `GET /action-center` loads all items (`.all()` at `:32`), optional status filter only. Severity: med. Recommendation: pagination + index on `status` (see §d).
3. `backend/app/api/routers/options.py:42` — `GET /options/positions` loads all positions (`.all()` at `:48`). Severity: low (small per-user sets today). Recommendation: limit 200 for consistency.
4. `backend/app/api/routers/watchlist.py:21` — `GET /watchlist` loads all watchlists, no limit. Severity: low. Recommendation: fine at current scale; add limit if symbols blobs grow.
5. `backend/app/api/routers/terminal.py:144` — `GET /terminal/analytics` loads entire order history (`.all()` at `:150`) and reconstructs equity in Python. Severity: med. Recommendation: aggregate in SQL (by day/side) or cap window (e.g. last 2y) + paginate.
6. `backend/app/api/routers/monitoring.py:39` — `GET /monitoring/latency` pulls all `(route, duration_ms)` rows in window into Python (`:47`, groups at `:49`). Severity: med. Recommendation: compute percentiles in SQL or cap rows (e.g. 20k) + shorten default window. `traffic` endpoint (`:77`) correctly aggregates in SQL — copy that pattern.
7. `backend/app/services/memory/store.py:66` — `list()` accepts `limit` and applies `stmt.limit(limit)` (`:80`), but `backend/app/api/routers/terminal.py:309` passes `limit=500` for the journal. Severity: low. Recommendation: default 100, paginate journal UI.
8. Good examples (keep): `predictions.py:33` (`.limit(200)`), `master_contract.py:32` (`limit(min(limit,200))`), `tradingagents/store.py:274` (`limit=50`), `historify.py:184` (`limit=50`), `historify/store.py:480` (clamp 500 at `:485`), `historify/store.py:224` (query clamp 5000 at `:237`).

## (c) N+1-style DB access patterns in routers/services

1. `backend/app/services/historify/store.py:173` — `ingest()` runs `_upsert_catalog_conn` (which does `SELECT MIN/MAX/COUNT` at `:319`) once per ingested record. Severity: high. Recommendation: upsert catalog once per (symbol, exchange, interval) batch after the loop.
2. `backend/app/services/historify/store.py:192` — `incremental_ingest()` does `SELECT COUNT(*)` per record to test existence. Severity: high. Recommendation: single `SELECT ts ... WHERE (symbol,exchange,interval) IN ...` or `INSERT ... ON CONFLICT DO NOTHING`, then count.
3. `backend/app/services/historify/store.py:446` — `create_job_items()` inserts job items one `execute` per symbol; `bulk_watchlist` (`:419`) calls `add_watchlist` per symbol, each opening/closing its own DuckDB connection (`:33`). Severity: med. Recommendation: executemany / single transaction.
4. `backend/app/services/historify/jobs.py:57` — `run_download_job` is serial per item: `get_job` (`:59`), `update_job_item` (`:76`), `get_history` (`:79`), `incremental_ingest` (`:84`), `refresh_catalog` (`:90`, itself a full `SELECT DISTINCT` + per-key agg at `store.py:358`), `update_job` (`:94`) — per symbol. Severity: high. Recommendation: concurrency cap (4–8) + batch catalog refresh at end.
5. `backend/app/services/historify/store.py:474` — `get_job()` always loads all `job_items` (no pagination). Severity: low. Recommendation: paginate items for large jobs.
6. `backend/app/services/autopilot/agents.py:142` / `:148` — sentinel does get+set on `memory_store` per position per cycle. `execute_agent` persists one order row per fill via `_persist_order_record` (`:476`, `:516`). Severity: low. Recommendation: batch memory writes; bulk-insert order records.
7. `backend/app/services/strategy_host/runner.py:388` — one watchdog `threading.Thread` per run + `time.sleep(0.2)` poll loop (`:320`). Severity: low (thread, not event-loop block). Recommendation: single shared timer or `threading.Event.wait(timeout)`.
8. No classic ORM lazy-N+1 (no lazy relationships traversed in loops) was found; relationships (`TradingRun.nodes`, `AutopilotRun.nodes`, `ScheduledResearch.runs`) are only loaded via explicit stores. Keep it that way.

## (d) Missing DB indexes on frequently-filtered columns

All models index `user_id` (good). Gaps are second-filter / ordering columns:

1. `backend/app/db/models/order.py:16` — `Order.symbol`, `:17 side`, `:20 status`, `:22 created_at` unindexed, yet filtered/ordered at `orders.py:295` (`user_id` + `created_at desc`), `orders.py:320` (`or_(id, extra_data)` — `extra_data` unindexed), `terminal.py:146` (`user_id` + `created_at asc`, plus Python-side `status == "filled"` at `:157`). Severity: high. Recommendation: composite `(user_id, created_at)`, index on `status`, consider index on `symbol`.
2. `backend/app/db/models/action_center.py:17` — `symbol`, `:21 status`, `:26 created_at` unindexed; filtered at `action_center.py:28`/`30` and ordered at `:31`. Severity: med. Recommendation: `(user_id, status, created_at)`.
3. `backend/app/db/models/portfolio.py:19` — `Holding.symbol` unindexed; looked up by `(user_id, symbol)` at `portfolio.py:69`, `trading.py:433`. Severity: med. Recommendation: unique-ish composite `(user_id, symbol)`.
4. `backend/app/db/models/prediction.py:21` — `symbol`, `:22 timeframe` unindexed; listed by `user_id` + `created_at desc` at `predictions.py:37`. Severity: low. Recommendation: `(user_id, created_at)`.
5. `backend/app/db/models/memory.py:22` — `key/kind/scope` unindexed except unique `(user_id, key)` (`:19`); filtered by kind/scope at `memory/store.py:76`/`78`. Severity: med. Recommendation: composite `(user_id, kind, scope, updated_at)`.
6. `backend/app/db/models/options.py:20` — `symbol` unindexed; listed by `user_id` + `created_at desc` at `options.py:46`. Severity: low. Recommendation: `(user_id, created_at)` + `symbol`.
7. `backend/app/db/models/trading.py:46` — `TradingRun.symbol`, `:53 status` unindexed; listed by `user_id` + `created_at` at `tradingagents/store.py:277`. Severity: low. Recommendation: `(user_id, created_at)` + `status`.
8. `backend/app/db/models/autopilot.py:23` — `AutopilotRun.status/mission` unindexed; `AutopilotRunNode` correctly indexes `run_id` (`:41`). Severity: low. Recommendation: `(user_id, status, started_at)` if dashboard filters by status.
9. `backend/app/db/models/schedule.py:27` — `next_run_at`/`enabled`, `:39 status` unindexed; scheduler scans due tasks. Severity: med. Recommendation: `(enabled, next_run_at)` + `(schedule_id, status)`.
10. `backend/app/db/models/flow_graph.py:19` — `name/enabled` unindexed; listing is by `user_id` (`flow/store.py:60`). Severity: low. Recommendation: `(user_id, updated_at)` if list grows.
11. `backend/app/db/models/watchlist.py:18` — only `user_id` indexed; fine for per-user lists. No change.

## (e) Streaming QuoteHub poll-loop cost model

Code: `backend/app/services/streaming/hub.py:21` (`POLL_INTERVAL_S = 2.0`), `:22 MAX_SYMBOLS_PER_CONN = 20`, `:46` `_poll_loop`, `:50` sequential `get_quote`, `:69` `_fanout`, `:80` `subscribe`, `:102` `status`.

- Cost per tick ≈ `S × (p99 get_quote latency incl. Yahoo retry/backoff)` because symbols are polled strictly sequentially (`:50`–`:52`), then `await asyncio.sleep(2.0)` (`:63`). With S=20 and 300 ms/quotes → ~6 s per sweep: the 2 s interval is not honored under load; ticks arrive late and staggered (later symbols starve). Severity: high.
- No global symbol cap: per-connection cap is 20, but union `S` across connections is unbounded (`:49`, `:103`). 50 connections × 20 = 1000 sequential quotes per sweep → loop never catches up; Yahoo throttling then cascades (`yahoo.py:70` sleeps). Severity: high.
- Cache interaction: `get_quote` TTL is 60 s (`service.py:97`), so a 2 s poll mostly hits the in-process cache after warmup — cheap when cache is warm, but cold-start and post-expiry bursts still hit providers synchronously. Cache itself is an unbounded-in-practice dict capped at 2048 with lazy eviction (`service.py:125`) — fine, but no per-symbol TTL jitter (thundering herd on expiry). Severity: med.
- `_fanout` (`:71`) iterates all subscriber queues per tick; slow consumers drop via bounded `QUEUE_SIZE=100` (`:23`, `:75`) — good (no backpressure), but `dropped_ticks` is a single global counter (`:39`, `:77`) so per-symbol/per-client diagnosis is impossible. Severity: low.
- `_latest` (`:35`, `:60`) never evicts — grows with distinct symbols ever subscribed. Severity: low.
- REST `GET /streaming/quotes/latest` (`streaming.py:86`) bypasses the hub and re-fans out N sequential quotes per request — a second, unthrottled path to the same providers. Severity: med.
- Recommendations: (1) cap global `S` (e.g. 200) + reject/trim subscribes over cap; (2) poll concurrently (`gather` + semaphore ~10) and measure sweep duration; (3) make interval adaptive (`max(2.0, sweep_time)`) or stagger symbols; (4) add TTL jitter + `stale-while-revalidate` for quotes; (5) per-symbol drop counters + sweep-duration metric; (6) evict `_latest` on unsubscribe when no remaining watcher.

## (f) DuckDB/Historify heavy paths

Connection handling: `store.py:33` opens a new DuckDB file connection per call (`duckdb.connect`), closed in `finally` — no pooling. Every ingest/query/job-item update pays open+DDL (`CREATE TABLE IF NOT EXISTS` ×6, `:35`–`:128`). Severity: med. Recommendation: single shared connection (DuckDB is in-process; serialize writes with a lock) or at minimum skip DDL after first init.

1. `store.py:145` `ingest()` — per-record INSERT + per-record catalog agg (`:173` → `:319` full `MIN/MAX/COUNT` scan of that series). 10k-bar import ≈ 10k aggregate scans. Severity: high. Fix as §c.1.
2. `store.py:179` `incremental_ingest()` — per-record existence `SELECT` (`:192`) + per-insert catalog agg. Severity: high. Fix as §c.2.
3. `jobs.py:45` `run_download_job()` — fully serial over items (`:57`), one provider history (default `period="5y"`, `:78`) + ingest + `refresh_catalog` (`:90`, full-table `SELECT DISTINCT` at `store.py:343` + per-key agg loop `:358`) per symbol. A 100-symbol job is hours on throttle. Severity: high. Recommendation: bounded concurrency + batch catalog refresh once at end + smaller default period.
4. `historify.py:29` `GET /historify/status` — calls `count()` (`store.py:245` full `COUNT(*)`) + `symbols()` (`:253` full `DISTINCT` scan) + `list_catalog()` (`:364` unbounded) on every call. Severity: med. Recommendation: serve from `data_catalog` summary table; paginate catalog.
5. `store.py:292` `find_gaps()` (route `:86`) — loads up to 5000 rows (`:293`) then Python date-parses each. Severity: low. Recommendation: cap + do gap detection in SQL (window `LAG`).
6. `store.py:612`/`623`/`635` FNO helpers — `DISTINCT underlying/expiry` scans + `list_symbol_metadata` unbounded (`:586`, route `:342`). Severity: low. Recommendation: paginate + index-equivalent ordering is fine for small metadata, but cap rows.
7. `historify.py:240`/`261` CSV/Parquet imports — `await file.read()` then synchronous `pd.read_csv`/`read_parquet` (`store.py:676`/`682`) on the event loop (see §g). Exports (`:282`, `limit=5000`) build full in-memory row lists then `write_csv`/`write_parquet` (`store.py:653`/`667`) + `FileResponse` on temp files never cleaned. Severity: med. Recommendation: `asyncio.to_thread` for pandas + stream responses + delete temp files after send.
8. `store.py:427` `create_job()` + `:446` inserts items one-by-one in separate connections. Severity: low. Fix as §c.3.

## (g) Synchronous blocking I/O inside async routes

Good news first: `YahooProvider` correctly offloads with `asyncio.to_thread` (`yahoo.py:228`, `:231`, `:234`, `:237`), as does `LocalProvider` (`local.py:95`, `:118`). The remaining blocks:

1. `yahoo.py:70` — `_retry` does `time.sleep(delay*(i+1))` (up to ~6 s total) inside the worker thread. Not an event-loop block, but it holds a thread per quote and multiplies sweep latency (§e). Severity: med. Recommendation: async sleep + fewer attempts for hub polls (fast path) vs interactive.
2. `historify/store.py:34` — `duckdb.connect` + DDL per call runs inline in async routes (`historify.py:29`, `:75`, `:184`, …). DuckDB calls are short but synchronous and frequent. Severity: med. Recommendation: `to_thread` or shared connection + init-once.
3. `historify/store.py:676` / `:682` / `:670` — `pd.read_csv` / `read_parquet` / `to_parquet`, plus `:659` file `open().write`, all called directly from async import/export routes (`historify.py:246`, `:268`, `:287`). Severity: med. Recommendation: wrap in `asyncio.to_thread`.
4. `backtesting/sandbox.py:290` — `subprocess.run(...)` (blocking wait, default `timeout` up to minutes) plus `:287` `df.to_csv` and `:288` file write, invoked synchronously from `POST /analysis/backtest` via `run_backtest_with_benchmark` (`analysis.py:769`). Significance: one backtest blocks the event loop worker for the whole subprocess duration. Severity: high. Recommendation: `await asyncio.to_thread(run_backtest_with_benchmark, ...)` (or a worker pool) + cap `period`/bars.
5. `analysis.py:407`–`:450` technical-series math (SMA/EMA/RSI/MACD/BB/Stoch/Supertrend/DMI/CCI/MFI/OBV/SAR/Ichimoku over full candle arrays, recomputing `rsi_series` twice at `:447`) runs inline in the route. Severity: low–med. Recommendation: `to_thread` for large `period`s + avoid duplicate series computation.
6. `strategy_host/runner.py:320` `time.sleep(0.2)` — runs in a dedicated watchdog thread (`:388`), not the event loop. No fix needed; note only.
7. `mcp/client.py:113` correctly uses `asyncio.create_subprocess_exec` — good pattern, no change.

Also note `streaming.py:109` and `:235` call `holiday_lookup(session, date(2000,1,1), date(2100,1,1))` — a 100-year DB range scan (`market_calendar.py:83`) on every REST call and every 60 s per `/market` WS connection. Severity: med. Recommendation: cache lookup (holidays change rarely) or narrow to ±1 year.

## (h) Test-suite timing note (~434 tests; slowest files)

Not measured: read-only audit, no suite executed, no servers started — so the ranking below is a static prediction, not a measurement. `backend/tests/conftest.py:1` uses a temp sqlite DB + maxed rate limits, and most tests monkeypatch market access (e.g. `test_autopilot.py:6`, `test_analysis_features.py:1`, `test_intraday_deep.py:3`), so the suite is designed to be fast. Likely slowest files on a real run:

1. `backend/tests/test_backtest_v2.py` — exercises the sandbox subprocess (`sandbox.py:290`) + metrics/validation over generated frames; subprocess spawn per case dominates. Predicted slowest.
2. `backend/tests/test_strategy_host.py` — spawns `multiprocessing` (spawn context, `runner.py:366`) per run + watchdog threads; process spawn cost on Windows dominates.
3. `backend/tests/test_autopilot.py` — full mission engine with many agents/services (still monkeypatched, but large fixture graph).
4. `backend/tests/test_trading_desk.py` — engine run graph + SSE paths.
5. `backend/tests/test_scanner_and_prediction.py` + `test_intraday_deep.py` — scanner/prediction over synthetic 1y histories (numpy/pandas per symbol).
6. `backend/tests/test_historify.py` + `test_historify_phase3.py` — DuckDB file IO per test (connect + DDL per op, §f).
7. `backend/tests/test_tradingview_provider.py` — provider parsing/network-shaped retries if not fully stubbed.

Recommendation: run `pytest -q --durations=20 -p no:cacheprovider` once to get the true ranking, then (a) mark subprocess/process-spawn tests `slow`, (b) share DuckDB temp file per module, (c) keep the existing monkeypatch discipline (never hit Yahoo in tests).

## Prioritized fix list (top 5)

1. Parallelize QuoteHub polling + cap global symbols (high). Fixes §e: `hub.py:46` gather+semaphore, global S cap, adaptive interval, per-symbol drop/sweep metrics. Without this, any WS adoption collapses the 2 s cadence and throttles Yahoo for everyone.
2. Batch the per-request quote fan-outs (high). Fixes §a.2–3, §a.7–8: `portfolio.py:27`, `terminal.py:75`/`261`, `deep/engine.py:79`, `quant.py:53` → `gather` + semaphore 8 + response cache. Biggest interactive-latency win.
3. Take backtests off the event loop (high). Fixes §g.4: wrap `run_backtest_with_benchmark` (`analysis.py:769`, `sandbox.py:290`) in `to_thread`/worker pool + cap input bars. One backtest currently stalls the loop for all users.
4. Fix Historify per-record DB round-trips (high). Fixes §c.1–2, §f.1–3: batch catalog updates, set-based existence check, concurrent job runner (4–8) + end-of-job catalog refresh. Turns 10k-bar imports and multi-symbol jobs from pathological to linear.
5. Add pagination + the missing composite indexes (high/med). Fixes §b.1, §c-monitoring, §d.1: `orders.py:289` limit/offset, `monitoring.py:39` SQL-side aggregation/row cap, `(orders user_id, created_at)` + `status`, `(action_center user_id, status, created_at)`, `(holdings user_id, symbol)`, `(agent_memories user_id, kind, scope)`, `(scheduled enabled, next_run_at)`. Cheap, prevents full-table scans as data grows.
