"""Security helpers: password hashing, JWT creation/verification, RBAC, secret encryption, TOTP."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from jose import JWTError, jwt
import pyotp

from app.core.config import settings

# --- Password hashing (Argon2 primary, bcrypt legacy) -------------------------

_PEPPER = None


def _pepper() -> str:
    global _PEPPER
    if _PEPPER is None:
        _PEPPER = getattr(settings, "password_pepper", "") or ""
    return _PEPPER


_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


def hash_password(password: str) -> str:
    """Hash a password with Argon2id + application pepper."""
    return _ph.hash((password or "") + _pepper())


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password, supporting Argon2 and legacy bcrypt hashes."""
    if not hashed:
        return False
    try:
        if hashed.startswith("$argon2"):
            _ph.verify(hashed, (plain or "") + _pepper())
            return True
        # Legacy bcrypt
        return bcrypt.checkpw((plain or "").encode("utf-8"), hashed.encode("utf-8"))
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
    except Exception:
        return False


def needs_rehash(hashed: str) -> bool:
    """True when a stored hash should be upgraded to the current algorithm."""
    if not hashed:
        return True
    if hashed.startswith("$2"):
        return True  # legacy bcrypt -> Argon2
    try:
        return _ph.check_needs_rehash(hashed)
    except Exception:
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


# --- Secret encryption (Fernet, PBKDF2 + per-install salt) -------------------


_salt_cache: bytes | None = None


def _salt_path() -> Path:
    url = settings.database_url
    if url.startswith("sqlite"):
        try:
            data_dir = Path(url.split("///")[-1]).parent
        except Exception:
            data_dir = Path(".")
    else:
        data_dir = Path(".")
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / ".stockos_fernet_salt"


def _fernet_salt() -> bytes:
    global _salt_cache
    if _salt_cache is not None:
        return _salt_cache
    env_salt = os.getenv("STOCKOS_FERNET_SALT")
    if env_salt:
        try:
            _salt_cache = base64.b64decode(env_salt)
            return _salt_cache
        except Exception:
            _salt_cache = env_salt.encode("utf-8")
            return _salt_cache
    path = _salt_path()
    if path.exists():
        try:
            _salt_cache = base64.b64decode(path.read_text(encoding="utf-8").strip())
            return _salt_cache
        except Exception:
            _salt_cache = path.read_bytes()
            return _salt_cache
    salt = secrets.token_bytes(16)
    path.write_text(base64.b64encode(salt).decode("ascii"), encoding="utf-8")
    _salt_cache = salt
    return _salt_cache


def _fernet() -> Fernet:
    """Fernet instance derived from the app secret via PBKDF2 (per-install salt)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_fernet_salt(),
        iterations=390_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.jwt_secret.encode("utf-8")))
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    """Encrypt a provider API key for persistence. Raise if empty."""
    if not value:
        raise ValueError("Nothing to encrypt (empty value)")
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a stored API key. Raises on wrong key/corruption."""
    return _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")


# --- TOTP 2FA ----------------------------------------------------------------


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, account_name: str, issuer: str = "StockOS AI") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return bool(pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1))
    except Exception:
        return False
