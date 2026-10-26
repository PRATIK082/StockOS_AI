# Phase 1 — Security and Auth: Concrete Implementation Tasks

Branch: `feature/openalgo-adaptation` (local only, not pushed)

## Scope for this iteration
Implement the security foundation (OpenAlgo-inspired) without breaking existing
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
- [ ] CSRF protection for cookie/session routes (if cookies are introduced).
- [ ] IP ban middleware for repeated failures.
- [ ] Session expiry + broker token revocation list.
- [ ] Frontend TOTP setup/verify UI.
- [ ] Security tests (rate limit, headers, Argon2, TOTP).

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
- `docs/openalgo-deep-study-and-implementation-plan.md`
