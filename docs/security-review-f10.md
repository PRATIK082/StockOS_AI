# Security Review — StockOS AI backend (`backend/app`) — F10 (flow + strategy-host suite)

- Scope: `backend/app` — auth (`api/deps.py`, `core/security.py`, `api/routers/auth.py`),
  routers, services (flow executor, strategy-host runner/store, backtesting sandbox),
  middleware (`core/middleware.py`, `core/csrf.py`, `core/rate_limit.py`, `core/ip_ban.py`),
  `main.py` wiring. Branch `feature/flow-strategy-suite`.
- Method: read-only. All `file:line` citations below were verified by reading the files.
  No source files edited, no servers started, no git commands run.
- Convention: **[VERIFIED]** = confirmed in code. **[NOTE]** = observation / defense-in-depth
  suggestion, not a confirmed vulnerability. Severities are the reviewer's judgment.
- No fixes implemented (per task).

## TL;DR — the short list

1. **CRITICAL [VERIFIED]** — `PATCH /api/v1/settings` (and GET) has **no authentication at all**:
   `backend/app/api/routers/settings.py:74-75,92-93` define endpoints with no `Depends`/user
   param (file imports nothing from `app.api.deps`). Any unauthenticated caller can flip
   `execution_mode` to `LIVE_ENABLED`, change broker, and loosen risk limits.
2. **CRITICAL [VERIFIED]** — any authenticated user gets **arbitrary server-side command execution**
   via MCP stdio: `backend/app/api/routers/mcp_client.py:16-23,40-49` accepts arbitrary
   `command`/`args`/`env`/`cwd` and `backend/app/services/mcp/client.py:106-120` runs them with
   `asyncio.create_subprocess_exec(*command, ...)` with inherited-plus-custom env. No admin gate.
3. **HIGH [VERIFIED]** — anonymous LLM spend: `POST /research` (`backend/app/api/routers/research.py:22-29`)
   and `POST /chat/vibe` (`research.py:64-91`) plus `GET /llm/*` (`research.py:94-126`) take **no user
   param at all**. Only `/chat` uses `OptionalUser`.
4. **HIGH [VERIFIED]** — rate limiting is effectively **unenforced**: `backend/app/main.py:80-82` sets
   `app.state.limiter` + exception handler but never adds SlowAPI's middleware, and only 2 routes
   in the whole codebase carry `@limiter.limit` (`backend/app/api/routers/auth.py:40,65`).
5. **HIGH [VERIFIED]** — backtest walk-forward executes user `custom_code` **in-process**:
   `backend/app/services/backtesting/engine_v2.py:219-223` calls `run_user_strategy(..., use_subprocess=False)`,
   bypassing the subprocess isolation that `backend/app/services/backtesting/sandbox.py:290-297` otherwise provides.
6. **HIGH [VERIFIED]** — strategy-host child runs **full unsandboxed Python** with the **full server
   environment**: `backend/app/services/strategy_host/runner.py:130-134` inherits `os.environ` and only
   adds keys; `runner.py:358-365` additionally injects `DATABASE_URL`; `runner.py:243-244` is a bare
   `exec(compile(code...))` with default builtins (no AST gate, unlike the backtesting sandbox).
7. **HIGH [VERIFIED]** — flow `live` order path has **no risk-engine checks** and the validator's
   `approval_unsafe` finding is **advisory only**: `backend/app/api/routers/flow.py:131-152` never calls
   `validate()`; `backend/app/services/flow/executor.py:327-376` places broker orders directly.
8. **HIGH [VERIFIED]** — `POST /terminal/tradebot/execute` claims "always PAPER"
   (`backend/app/api/routers/terminal.py:401-409`) but uses `orders._get_broker`
   (`terminal.py:417-420`, `backend/app/api/routers/orders.py:32-36`), which honors
   `selected_execution_broker` — in `LIVE_ENABLED` mode this path goes live.

---

## (a) Authentication / authorization gaps

### A1. Unauthenticated settings mutation — CRITICAL [VERIFIED]

- `backend/app/api/routers/settings.py:74-75` (`get_settings_endpoint`) and `:92-93` (`update_settings`)
  have **no dependency on any auth object**; the module imports nothing from `app.api.deps`
  (verified by grep: only matches are the two `@router` lines and the two `def` lines).
- `update_settings` (`settings.py:99-118`) mutates the global settings singleton, including
  `execution_mode`, `selected_execution_broker`, `max_*` risk limits, and `analyzer_mode`, with no
  validation of `execution_mode`/`broker` values against the allowed sets (pydantic model documents
  them as free `str | None`, `settings.py:30-36`).
- There is no global auth dependency in `backend/app/main.py:103-104` (`app.include_router(api_router, ...)`,
  no `dependencies=`).
- Recommendation: require `CurrentUser` (at minimum) and `AdminUser` for PATCH; validate values against
  the same allowlists as `core/config.py:44-56`; audit-log changes.

### A2. Anonymous orchestrator/LLM routes — HIGH [VERIFIED]

- `backend/app/api/routers/research.py:22-23`: `POST /research` signature is
  `async def research(body: ResearchRequest) -> dict` — no user. It runs the agent orchestrator
  (`research.py:24-28`), i.e. anonymous callers can burn LLM/data-provider budget (DoS-by-spend).
- `research.py:64-65`: `POST /chat/vibe` likewise takes only `body: ChatRequest` and streams
  `vibe_chat_engine.stream(...)` (`research.py:76-91`). Read-only analysis (vibe engine has no
  `place_order`/`get_broker`/approval references — verified by grep, no matches), so no order risk,
  but still unauthenticated compute spend.
- `research.py:94-126`: `GET /llm/providers|models|registry`, `GET /models/registry` — no user.
  Low sensitivity (provider list), but inconsistent with the authenticated `/trading/providers`
  (`backend/app/api/routers/trading.py:74-76`).
- `POST /chat` (`research.py:32-33`) correctly uses `OptionalUser` and degrades attachments for
  anonymous callers (`research.py:37-46`). No change needed there.
- Recommendation: gate `/research` and `/chat/vibe` behind at least `OptionalUser` with anonymous
  rate caps, or `CurrentUser` to match the rest of the AI surface.

### A3. Public read-only market data — LOW / design note [VERIFIED, NOTE]

- `backend/app/api/routers/market.py:14-68` (quote/history/fundamentals/health/status/sources) and
  `backend/app/api/routers/instruments_new.py:15-122` (search/indices/market/symbol/all/sectors) import
  nothing from `app.api.deps` and take no user param. All are GETs with no state change; upstream
  provider cost is the only exposure.
- Recommendation: keep public if intentional, but document it and consider caching/rate caps once
  rate limiting is actually enforced (see F1).

### A4. `AdminUser` / `CurrentUser = None` pattern — NOT a bypass [VERIFIED, NOTE]

- Several routes declare `user: CurrentUser = None  # type: ignore[assignment]`
  (`backend/app/api/routers/strategy_host.py:137,193`,
  `action_center.py:25,74`, `agent_extras.py:23,38,57,62,70,81`, `calendar.py:32,86,93`,
  `streaming.py:70`, `telegram.py:41`) and admin routes declare `user: AdminUser = None`
  (`backend/app/api/routers/brokers.py:183`, `telegram.py:48,62,71`, `calendar.py:42,61`).
- Verified `AdminUser = Annotated[User, Depends(require_role("admin"))]` (`brokers.py:29`,
  `telegram.py:21`, `calendar.py:21`) where `require_role` builds a guard over `CurrentUser`
  (`backend/app/api/deps.py:73-79`), and `get_current_user` raises 401 without/invalid credentials
  (`deps.py:19-36`). In FastAPI the `= None` default does **not** skip the dependency — the guard
  still runs, so unauthenticated callers still get 401 and non-admins 403. This is a type-hygiene
  smell, not an auth bypass. (Direct in-process calls passing `user=None` would fail with
  `AttributeError` on `user.id`, i.e. a 500, not a bypass.)
- Recommendation: drop the `= None` defaults so signatures honestly require auth; keep the
  `AdminUser` alias pattern (it is used correctly everywhere it appears).

### A5. Per-user scoping is otherwise consistent [VERIFIED, NOTE]

- Flow store (`backend/app/services/flow/store.py:58-72`), strategy-host store
  (`backend/app/services/strategy_host/store.py:69-83`), orders (`backend/app/api/routers/orders.py:289-338`),
  action-center (`backend/app/api/routers/action_center.py:28,56-57,77-78,98-99`), and trading runs
  (`backend/app/api/routers/trading.py:323-338`) all filter by `user.id`. No IDOR found in the
  reviewed paths: cross-user access returns 404, never another user's row.

---

## (b) Strategy-host script-runner sandbox boundary

Implementation: `backend/app/services/strategy_host/runner.py`, store
`backend/app/services/strategy_host/store.py`, routes `backend/app/api/routers/strategy_host.py`.

### B1. Child is a full Python interpreter, not a sandbox — HIGH [VERIFIED]

- `_child_main` (`runner.py:119-259`) executes user code via bare
  `exec(compile(code, "strategy.py", "exec"), gl)` (`runner.py:243-244`) where
  `gl = {"ctx": _Ctx(), "__name__": "__main__"}` (`runner.py:243`) — **default `__builtins__`**,
  no import restrictions, no AST validation (contrast the backtesting sandbox allowlist,
  `backend/app/services/backtesting/sandbox.py:134-170`). User code can `import os/socket/subprocess`,
  read files, and open network connections.
- Isolation is exactly one OS process boundary: `multiprocessing` spawn context (`runner.py:366-367`),
  per-run dir `backend/data/strategy_runs/<run_id>/` (`runner.py:60-64,352-356`, `run_id = uuid4().hex`,
  `runner.py:352`), hard timeout `MIN 1s / DEFAULT 120s / MAX 600s` with watchdog kill
  (`runner.py:49-51,316-329,342-343`), single-run-per-script-per-user guard (`AlreadyRunning`,
  `runner.py:344-351`).
- What it CAN touch: same UID's filesystem, network, `ctx.history` market-data facade
  (`runner.py:179-204`), `ctx.place_order` intent file (`runner.py:206-239`), the entire inherited
  process environment (below), CPU/memory/disk up to host limits (no cgroup/rlimit/quota — no such
  code in `runner.py`).
- What it CANNOT touch directly: parent-process memory (spawn, not fork — `runner.py:366`);
  the broker (children only append JSONL intents, `runner.py:233-236`; fills happen parent-side in
  `_file_intent`, `runner.py:458-546`). Order *impact* is still reachable indirectly via intents.
- Recommendation: treat strategy code as untrusted-hostile: scrub env (B2), add CPU/RSS/file-size
  rlimits + a global concurrency cap, run under a dedicated low-privilege user/chroot/container,
  and add an AST gate similar to `sandbox.py:134-170` (or at minimum block `import` of
  `os/sys/subprocess/socket/pathlib` and dunder access).

### B2. Child inherits the full server environment incl. DB URL — HIGH [VERIFIED]

- `_child_main` only *adds* keys (`runner.py:132-134`:
  `os.environ[key] = value` for identifier-safe keys) and *adds* `DATABASE_URL` from the payload
  (`runner.py:130-131`); it never scrubs. Spawned children inherit the parent's `os.environ`, so
  secrets present as env vars (LLM keys, `STOCKOS_*`) are visible to user code via `os.environ`.
- `start_run` ships `database_url=get_settings().database_url` from the route
  (`strategy_host.py:145-152` → `runner.py:358-365`). For the default sqlite URL the child can open
  the app DB file directly (same UID), bypassing API authZ entirely (read tables, and write unless
  the file is read-only — it is not made read-only anywhere in `runner.py`).
- Env-blob handling itself is sound: Fernet-encrypted JSON blob (`store.py:158-190`, caps
  `MAX_KEYS=50 / MAX_KEY_LEN=64 / MAX_VALUE_LEN=8192`, `store.py:28-30`), key validation
  (`store.py:134-139`), names-only GET (`strategy_host.py:211-218`, returns `{"keys": keys}`),
  values passed to the child as `secrets` for redaction (`runner.py:358-365`).
- Recommendation: pass only an explicit allowlist (`{DATABASE_URL? no — child has no DB need; drop it}`
  + script env), i.e. `os.environ.clear()` + minimal `PATH`/stub in the child; never forward the DB URL
  to user code; store the sqlite file with least privilege.

### B3. Log caps + redaction — sound with a documented hole [VERIFIED, NOTE]

- Caps: `MAX_LOG_BYTES = 256KB` with truncation note (`runner.py:52-53,158-171`),
  `MAX_LOG_LINES = 2000`, read `tail` clamped to `[1, 2000]` (`runner.py:614`).
- Redaction: `redact_text` replaces every stored secret value (`runner.py:67-73`), applied on write
  in the child (`runner.py:162`) and again on read (`runner.py:624`); values shorter than
  `REDACT_MIN_LEN = 4` are skipped (`runner.py:54,71`) — documented, but short secrets/tokens can leak
  into logs. `print` output is captured into the same log (`runner.py:153-154`).
- Recommendation: keep dual redaction; warn users against short secret values (or refuse env values
  shorter than e.g. 8 chars); consider also redacting `DATABASE_URL` and known token patterns.

### B4. No global concurrency / resource caps [VERIFIED, NOTE]

- `AlreadyRunning` is per `(user_id, script_id)` (`runner.py:344-351`); nothing caps total processes,
  CPU time, RSS, output-file growth rate, or `orders.jsonl` length. Each run also appends filed-intent
  lines to `log.txt` parent-side (`runner.py:572-577`, capped only by the child's byte cap on its own
  writes — parent appends bypass the cap).
- Recommendation: global semaphore on concurrent runs, per-run intent-count cap, rlimits in the child.

---

## (c) Flow executor order path — approval gating

Implementation: `backend/app/services/flow/executor.py`, routes `backend/app/api/routers/flow.py`,
validator `backend/app/services/flow/validator.py`, schemas `backend/app/services/flow/schemas.py`.

### C1. Validator approval finding is advisory; run path never calls it — HIGH [VERIFIED]

- `validator.py:192-202` emits `approval_unsafe` when an order node sets `live: true` without
  `require_approval: true`.
- But `POST /flow/run` (`flow.py:131-152`) only calls `_reject_unknown_types(graph)` (`flow.py:150`)
  then `run_graph(...)` (`flow.py:151`) — `validate()` is only exposed via the separate
  `POST /flow/validate` (`flow.py:119-128`). A `live: true` graph runs without any approval error,
  and the executor itself never inspects `params.require_approval` (verified: no `require_approval`
  reference in `executor.py`).
- Recommendation: enforce in `run_graph`/`run_flow`: refuse `live` order nodes unless approval routing
  applies, or at minimum surface validator findings in the run response and block on `approval_unsafe`.

### C2. Live flow orders skip the risk engine — HIGH [VERIFIED]

- Executor live path (`executor.py:327-376`): builds broker via
  `broker_name = "paper" if paper_only else settings.selected_execution_broker` (`executor.py:330`)
  and calls `broker.place_order(...)` (`executor.py:333-340`) with no `RiskEngine.check_order`,
  no quantity/daily-loss/position caps. Contrast `/v1/orders/submit`, which risk-checks before submit
  (`orders.py:161-174`) and routes approval mode to Action Center (`orders.py:134-153`).
- `paper_only` is user-mutable via `PATCH /flow/graphs/{id}` (`flow.py:85-106` +
  `store.py:update_graph` handling `paper_only`), so a user can flip a graph to live-capable; in
  `LIVE_ENABLED` global mode that means real fills with no per-order risk check.
- Dry-run is safe (`executor.py:281-287`, simulated only); approval mode correctly files
  `ActionCenterItem(pending)` and never fills (`executor.py:293-325`); condition-gating only skips
  orders on explicit upstream `False` (`executor.py:241-251`) — orders still fire when upstream data
  is `empty`/`error` (null), which should be a conscious product decision.
- Recommendation: run the same `RiskEngine.check_order` + global halt checks as `/v1/orders` in the
  executor live path; require admin/approval to set `paper_only=false`; treat null upstream inputs
  as blocking for live orders.

### C3. Approval state machine itself is correct [VERIFIED, NOTE]

- `POST /action-center/{id}/approve` sets `approved` (`action_center.py:50-67`),
  `.../reject` sets `rejected` (`action_center.py:70-89`), and `.../execute` requires
  `status == "approved"` (`action_center.py:103-104`) before executing via the configured broker
  (`action_center.py:106-178`) and persisting fills (`action_center.py:187-203`). No
  approve-and-execute shortcut; all queries are user-scoped. No issue found here.
- Strategy-host intent filing mirrors this correctly: approval mode → pending item (`runner.py:481-500`),
  otherwise **paper broker only** regardless of global mode (`runner.py:507`). Note the asymmetry:
  strategy-host can never go live (safe default) while flow can (C2).

---

## (d) Secret handling

### D1. Fernet/PBKDF2 construction — solid, one key-management caveat [VERIFIED]

- `encrypt_secret`/`decrypt_secret` (`security.py:236-245`) use Fernet with a key derived via
  PBKDF2-HMAC-SHA256, 390k iterations, per-install salt (`security.py:224-233`, salt in
  `security.py:198-221`: `STOCKOS_FERNET_SALT` env or `.stockos_fernet_salt` file beside the DB).
- Caveat [VERIFIED]: the KDF password is `settings.jwt_secret` (`security.py:232`), whose default is
  `"super-secret-key-change-me"` (`core/config.py:80`). Any install that never sets
  `STOCKOS_JWT_SECRET` has trivially re-derivable at-rest encryption for broker keys, TOTP seeds,
  telegram tokens, and strategy env blobs. The salt file living next to the sqlite DB also means a
  DB-file theft usually yields the salt too (still needs the JWT secret, but see default).
- Recommendation: fail-closed on default `jwt_secret` (refuse to start in production / auto-generate
  and persist), support separate `STOCKOS_FERNET_PASSWORD`, document salt backup.

### D2. No secret echo in APIs — VERIFIED GOOD (with one by-design exception)

- Strategy-host env GET returns names only (`strategy_host.py:211-218`, comment "NAMES ONLY").
- Broker diagnostics returns only Y/N flags + last-auth outcome (`brokers.py:58-83,99-108`); credentials
  write-only (`brokers.py:111-131`); `verify_auth` decrypts in memory, never returns secrets
  (`brokers.py:146-176`); TOTP seed write-only + base32-validated (`brokers.py:179-199`).
- Telegram status omits the token (`telegram.py:30-37,40-44`); token write-only/clearable
  (`services/telegram/config.py:25-44`); decrypt failures degrade to `None` without logging the value
  (`config.py:47-55`).
- Trading credentials list exposes only `has_key` + metadata (`services/tradingagents/store.py:87-95,165-175`);
  per-request keys fill in server-side, never echoed (`store.py:112-162`).
- By-design exception [NOTE]: `POST /auth/totp/setup` returns the raw `secret` + provisioning URI
  (`auth.py:138-149`, schema `api/schemas.py:32-35`). Expected for enrollment, but the secret is
  persisted **before** verification (`auth.py:140-143`) and re-returned on every call until enabled —
  no rotation/expiry. Recommend single-show + rotate-on-re-setup and expire unverified secrets.

---

## (e) Injection risks

### E1. SQL — no issue found [VERIFIED, NOTE]

- Grep for `text(`, `execute(`-with-raw, `from_statement`, `where(text`, f-string `SELECT` across
  `backend/app/api` found only ORM `select(...)` / `insert(...)` with bound parameters
  (representative: `orders.py:201-216,244-255`, `calendar.py:47,66`, `brokers.py:50-55`). No raw SQL
  sink found. SQLAlchemy usage is parameterized throughout the reviewed paths.

### E2. Command execution — MCP stdio is intentional RCE for any authenticated user — CRITICAL [VERIFIED]

- `mcp_client.py:16-23` (`StdioConnectRequest`: free-form `command: list[str] | str`, `args`, `env`,
  `cwd`) → `connect_stdio` (`mcp_client.py:40-49`) → `MCPClientService.connect_stdio`
  (`services/mcp/client.py:347-360`) → `asyncio.create_subprocess_exec(*self.command, ...)`
  with merged env and caller-chosen `cwd` (`client.py:106-120`). No admin/role gate (route uses plain
  `CurrentUser`), no allowlist, no sandbox. Any authenticated user (including self-registered, since
  `/auth/register` is open, `auth.py:39-61`) gets code execution as the server UID.
- SSE variant (`mcp_client.py:52-59`) is a lesser SSRF-ish concern (server fetches arbitrary URL).
- Recommendation: restrict `/mcp/clients/stdio` to admins, add a command allowlist + `cwd` jail,
  strip env inheritance, or remove the endpoint if unused.

### E3. Path traversal — guarded where user input reaches disk [VERIFIED, NOTE]

- Attachments: filename sanitized (`services/agents/attachments.py:116`), stored name
  `{uuid}_{safe}` (`attachments.py:117-118`), verified with `dest.resolve().parent == user_dir.resolve()`
  (`attachments.py:121-122`); `user_id` sanitized for the directory (`attachments.py:51-56`); caps
  10MB/file, 20 files/user, 20k extraction chars (`attachments.py:25-28`); suffix allowlist enforced
  (`attachments.py:108-110`). `load_texts`/`delete_attachment` resolve only via the index's stored names
  (`attachments.py:147-179`; `delete` uses `unlink(missing_ok=True)` on two derived names — safe given
  the write-time guard). No traversal found.
- Strategy runs: `run_dir = runs_root() / run_id` with server-generated `uuid4().hex` (`runner.py:352-354`);
  no user input in paths. `read_logs` disk fallback (`runner.py:596-613`) builds paths from the
  registry-supplied `run_id`; the router only ever passes the latest run of a user-owned script
  (`strategy_host.py:196-204`), so cross-user log reads were not found (fallback itself doesn't
  re-check `user_id` — harmless in current call graph, worth a defensive check).
- Recommendation: add the `user_id` assertion in the `read_logs` fallback; nothing else required here.

### E4. Code-execution sinks inventory [VERIFIED]

- Backtesting sandbox: AST-gated (`sandbox.py:134-170`: no imports/lambda/class/try/raise/with,
  dunder/private attrs blocked, call allowlist) + subprocess with timeout (`sandbox.py:290-297`),
  result via stdout JSON. Solid — **except** the walk-forward path forces `use_subprocess=False`
  (B5/C-attr: `engine_v2.py:219-223`), running the same user code **in the API process**.
- Strategy-host: no AST gate at all (B1).
- Flow conditions: whitelisted operator map, never `eval` (`executor.py:31-42,208-238`). Good.
- Voice STT: suffix allowlist + 25MB cap (`services/voice/stt.py:22-23`); route derives suffix from
  `file.filename` (`agent_extras.py:26-27`) — note: suffix is only used to pick a temp-file extension
  for whisper; no exec sink. Fine.

### E5. Unbounded user-controlled blobs — MEDIUM [VERIFIED, NOTE]

- Strategy `code` has **no size cap** in the strategy-host path: `store.create_script`
  (`services/strategy_host/store.py:47-66`) and `update_script` (`store.py:86-105`) accept arbitrary
  `code` (contrast backtesting `MAX_CODE_CHARS = 40_000`, `sandbox.py:28`). Large blobs bloat the DB
  and the child `compile()` (CPU DoS).
- Flow `GraphCreate.inline_graph`/`graph` lists are unbounded (`services/flow/schemas.py:39-43,67-72`);
  `/flow/import` persists arbitrary validated JSON (`flow.py:155-175`). Same DoS-by-size class.
- Recommendation: cap code (e.g. 40–100KB, matching sandbox), cap nodes/edges counts and `params` depth.

---

## (f) Rate limiting / CSRF / CORS / security headers

### F1. Rate limiting not enforced — HIGH [VERIFIED]

- `main.py:80-82` registers `app.state.limiter` + the 429 handler but **never adds SlowAPI middleware**
  (no `SlowAPIMiddleware` anywhere in `main.py`; verified lines 80-85 show only
  `SecurityHeadersMiddleware`, `CSRFMiddleware`, `MetricsMiddleware`). Without the middleware,
  `@limiter.limit` decorators are inert — and only `POST /auth/register` and `POST /auth/login`
  carry one (`auth.py:40,65`, budget `rate_limit_auth_per_minute = 10`, `config.py:84`). Everything
  expensive (backtest, flow run, strategy run, MCP connect, trading analyze, chat/research) is
  effectively unlimited; brute force on TOTP verify/disable endpoints is not rate-limited either.
- `ip_ban` (`core/ip_ban.py:47-76`, threshold 5 / 15-min window, `config.py:85-86`) is only consulted
  on `/login` (`auth.py:71-74,80-98,100-101`). In-memory per-process (`ip_ban.py:15`, `security.py:103`
  for the token blacklist) — restarts/multi-workers reset it.
- Recommendation: add `SlowAPIMiddleware`, set per-route budgets (esp. auth/TOTP/AI/compute/MCP),
  and back `ip_ban`/revocation with shared storage (or at minimum document single-process assumption).

### F2. CSRF — reasonable for a bearer API, two cookie flags [VERIFIED, NOTE]

- Double-submit cookie design (`core/csrf.py:38-69`): state-changing requests bearing a CSRF cookie
  must present the matching header (`csrf.py:59-68`); bearer clients exempt (`csrf.py:51-53` — correct,
  `Authorization` isn't auto-sent); no-cookie requests pass through (`csrf.py:60-62`, backward compat).
- Cookie flags: `httponly=False` (required for double-submit JS read) but also `samesite="lax"` with
  **no `Secure` flag** (`auth.py:121-124`, `main.py:97-101`). Over plain HTTP the token cookie is
  sniffable (mitigated once TLS is enforced — see HSTS below).
- Recommendation: add `Secure` when serving HTTPS (or always, if HTTP is dev-only); keep the
  bearer exemption; consider requiring CSRF for cookie-only session flows if those are ever added.

### F3. CORS — broad by design for LAN use; tighten if possible [VERIFIED, NOTE]

- `main.py:60-78`: explicit origins default to localhost dev ports + `CORS_ALLOWED_ORIGIN_REGEX`
  defaulting to a LAN matcher (`10/8`, `172.16-31`, `192.168/16`, any port), `allow_credentials=True`
  (since no `*`), `allow_methods` includes PATCH/DELETE, `allow_headers=["*"]`, `expose_headers=["*"]`.
  Any website reachable by a LAN client could make credentialed cross-origin calls; actual impact is
  bounded because auth is bearer-based (not auto-sent) and CSRF middleware still demands the header
  match for cookie flows — but `allow_headers=["*"]` lets an attacker-supplied origin send the
  `X-CSRF-Token` header via preflight, so the remaining protection is Same-Origin-Policy on *reading*
  the cookie value (attacker can't read it cross-origin) — sound as long as no token/secret is ever
  returned cross-origin-readable (see D2 — currently good).
- Recommendation: pin production `CORS_ALLOWED_ORIGINS` to the real frontend origin(s), unset the LAN
  regex in production, narrow `allow_headers`/`expose_headers` to what's needed.

### F4. Security headers — present, gaps: HSTS + CSP strictness [VERIFIED, NOTE]

- `SecurityHeadersMiddleware` (`core/middleware.py:10-26`) sets `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and a CSP that still allows
  `'unsafe-inline' 'unsafe-eval'` for scripts plus `connect-src` limited to self/localhost WS/HTTP.
  Missing: **`Strict-Transport-Security`** (no HSTS anywhere — verified by reading `middleware.py` in
  full), and the CSP `connect-src` doesn't cover the LAN origins CORS allows (frontend on a LAN IP
  would be blocked by its own CSP when calling the API — likely needs aligning).

---

## (g) TOTP / JWT / logout edge cases

### G1. TOTP enrollment weaknesses — MEDIUM [VERIFIED]

- Secret persisted **before** verification and re-served indefinitely: `totp_setup` generates +
  commits when absent (`auth.py:140-143`), then returns the same secret on every call
  (`auth.py:144-149`). An attacker with a stolen (but 2FA-less) session can enroll at leisure; there
  is no verification deadline or rotation.
- `verify`/`disable` correctly require a valid code (`auth.py:160-164,175-180`); `verify_totp` uses
  `valid_window=1` (`security.py:259-264`, i.e. ±1 step — standard); login correctly rejects
  missing/invalid 2FA codes (`auth.py:94-98`); codes are length-checked 6–8 chars (`schemas.py:38-39`).
- No rate limit / ip-ban on `totp_verify`/`totp_disable`/login-2FA beyond the login-route limiter
  (see F1) — a 6-digit code is guessable with unlimited attempts (windowed, but online guessing with
  no throttle is a real weakness).
- Recommendation: single-show secret + rotate on re-setup, expiry for unverified secrets, rate-limit +
  lockout on 2FA failures, require password re-entry for enroll/disable.

### G2. JWT/logout: blacklist is in-memory only — MEDIUM [VERIFIED]

- Tokens: HS256, `sub/role/iat/exp(30m default)/jti` (`security.py:76-90`, `config.py:79-82`);
  `decode_token` returns `None` on any `JWTError` (`security.py:93-97`); `get_current_user` enforces
  revocation + `is_active` (`deps.py:19-36`); `get_optional_user` degrades to anonymous on any error
  (`deps.py:42-67`) — correct for public chat, and it never elevates.
- `logout` revokes the presenting `jti` with exp-based TTL (`auth.py:127-135` → `security.py:118-133`).
  But storage is a **process-local dict** (`security.py:103,131`): restarts wipe it (logged-out tokens
  become valid again until `exp`), and multi-worker deployments don't share revocations. No refresh
  tokens — blast radius is capped at the 30-min access-token lifetime.
- `role_at_least` (`security.py:162-166`): unknown actual role maps to level 0 (deny — good); unknown
  *required* role maps to 999 (deny — good). RBAC helper is fail-closed.
- Recommendation: shared revocation store (or short exp + refresh rotation); document restart behavior.

### G3. Password handling — GOOD with minor notes [VERIFIED, NOTE]

- Argon2id (`time_cost=3, memory_cost=64MB`, `security.py:37`) + pepper (`security.py:30-43`), legacy
  bcrypt verify path + transparent rehash on login (`security.py:45-70`, `auth.py:89-91`). Good.
- Notes: legacy bcrypt branch verifies **without** pepper (`security.py:54`) — fine iff legacy hashes
  were pepper-less, but confirm; `RegisterRequest` allows 6-char passwords (`schemas.py:14-17`) with no
  breach/complexity screening; no email verification — open registration (`auth.py:39-61`) + default
  role `"user"` (`db/models/user.py:17`, verified via grep) means any internet user gets an
  authenticated account (amplifies E2/MCP and spend findings). Consider registration throttling,
  captcha/invite, or disabling open register in production.

### G4. Streaming WS auth — reasonable [VERIFIED, NOTE]

- WS uses `?token=` (browsers can't set headers — documented, `streaming.py:1-9`); `_ws_user`
  validates signature/expiry/revocation/`is_active` (`streaming.py:47-61`); bad tokens are
  accept-then-close-4401 (`streaming.py:34-35` + docstring). Token-in-URL risks log retention —
  acceptable trade-off, noted. REST streaming endpoints use `CurrentUser` (`streaming.py:69-78).

---

## Appendix — files reviewed (all read, not just grepped)

`app/api/deps.py`, `app/core/security.py`, `app/core/config.py`, `app/core/middleware.py`,
`app/core/csrf.py`, `app/core/rate_limit.py`, `app/core/ip_ban.py`, `app/main.py`,
`app/api/routers/__init__.py`, `auth.py`, `settings.py`, `strategy_host.py`, `flow.py`, `orders.py`,
`trading.py`, `action_center.py`, `brokers.py`, `telegram.py`, `calendar.py`, `terminal.py`,
`agent_extras.py`, `research.py`, `streaming.py`, `scheduled.py` (grep), `quant.py` (grep),
`market.py` (grep), `instruments_new.py` (grep), `mcp_client.py`, `analysis.py` (backtest region),
`app/services/flow/executor.py`, `validator.py`, `schemas.py`, `store.py`,
`app/services/strategy_host/runner.py`, `store.py`,
`app/services/backtesting/sandbox.py`, `engine_v2.py` (walk-forward region),
`app/services/mcp/client.py`, `app/services/telegram/config.py`,
`app/services/agents/attachments.py`, `app/services/tradingagents/store.py` (credentials region),
`app/services/voice/stt.py` (caps region), `app/services/scheduler/*` (grep),
`app/api/schemas.py` (auth region), `app/db/models/user.py` (grep).

Out of scope / not verified: frontend, broker SDK implementations (`brokers/zerodha|angelone`),
data-provider correctness, test suite, deployment/TLS config, prototype `engine.py` backtest path
(only `engine_v2.py` walk-forward region was checked for the subprocess flag).
