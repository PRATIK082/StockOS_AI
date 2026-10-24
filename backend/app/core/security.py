"""Security helpers: password hashing, JWT creation/verification, RBAC."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.core.config import settings

# --- Passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# --- JWT ---------------------------------------------------------------------


def create_access_token(subject: str, role: str, extra: dict[str, Any] | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


# --- RBAC ---------------------------------------------------------------------

ROLE_LEVELS = {"user": 1, "analyst": 2, "admin": 3}


def role_at_least(required: str, actual: str) -> bool:
    return ROLE_LEVELS.get(actual, 0) >= ROLE_LEVELS.get(required, 999)


def create_audit_entry(user_id: str, action: str, resource: str) -> dict[str, Any]:
    """Build a normalized audit log payload for the audit trail."""
    return {
        "user_id": user_id,
        "action": action,
        "resource": resource,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# --- Secret encryption (Fernet) ---------------------------------------------------


def _fernet() -> Fernet:
    """Deterministic Fernet key derived from the app secret (never stored in the DB)."""
    digest = hashlib.sha256(f"stockos:trading:{settings.jwt_secret}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    """Encrypt a provider API key for persistence. Raise if empty."""
    if not value:
        raise ValueError("Nothing to encrypt (empty value)")
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a stored API key. Raises ``cryptography.fernet.InvalidToken`` on wrong key/corruption."""
    return _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
