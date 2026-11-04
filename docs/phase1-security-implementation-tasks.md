# Phase 1 — Security and Auth: Concrete Implementation Tasks

Branch: `StockAlgo_1`

## Scope for this iteration
Implement the security foundation (adapted from a reference design) without breaking existing
StockOS auth/tests.

## Completed
- [x] Add dependencies: `argon2-cffi`, `slowapi`, `pyotp`.
- [x] Implement Argon2id password hashing with optional pepper (`core/security.py`).
- [x] Keep bcrypt verification for legacy hashes; transparent rehash on login.
- [x] Upgrade Fernet secret encryption to PBKDF2 + per-install salt.
- [x] Add rate limiting (slowapi) with configurable limits.
- [x] Apply rate limits to `/auth/register` and `/auth/login`.
- [x] Add security headers middleware (CSP, X-Frame-Options, etc.).
- [x] Add TOTP 2FA: user model fields, setup/verify/disable endpoints, login enforcement.
- [x] Add `/auth/me` TOTP status.
- [x] Update conftest for high test rate limits.
- [x] All 260 backend tests pass.

## Next (Phase 1 remainder)
- [x] CSRF protection for cookie/session routes (if cookies are introduced). (done: `core/csrf.py` middleware + `/api/csrf*` + `/api/auth/csrf*`; Bearer-token clients exempt).
- [x] IP ban middleware for repeated failures. (done: `core/ip_ban.py`, 5 fails / 15 min → 429.)
- [x] Session expiry + broker token revocation list. (done: 30-min JWT exp + jti blacklist + `POST /auth/logout`.)
- [x] Frontend TOTP setup/verify UI. (done: settings 2FA card + login 2FA field.)
- [x] Security tests (rate limit, headers, Argon2, TOTP). (done: `tests/test_security_phase1_remaining.py`.)

## Files touched
- `backend/pyproject.toml`, `backend/uv.lock`
- `backend/app/core/security.py`
- `backend/app/core/config.py`
- `backend/app/core/middleware.py`
- `backend/app/core/rate_limit.py`
- `backend/app/main.py`
- `backend/app/db/models/user.py`
- `backend/app/api/schemas.py`
- `backend/app/api/routers/auth.py`
- `backend/tests/conftest.py`
- `docs/reference-platform-study-and-implementation-plan.md`
