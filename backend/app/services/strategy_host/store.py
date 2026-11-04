"""CRUD + encrypted-env helpers for StrategyScript rows (Phase 8).

All helpers are user-scoped. Env vars are stored as a single Fernet-encrypted
JSON blob on the script row (``env_encrypted``), using
``app.core.security.encrypt_secret`` / ``decrypt_secret`` — the exact same
pattern as stored broker credentials. Values are only ever decrypted
server-side (to inject into the out-of-process worker); API layers must use
:func:`get_env_keys` (names only).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.strategy_script import StrategyScript

logger = get_logger("strategy_host.store")

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_KEYS = 50
MAX_KEY_LEN = 64
MAX_VALUE_LEN = 8192


def to_dict(row: StrategyScript) -> dict[str, Any]:
    created = row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at
    updated = row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else row.updated_at
    return {
        "id": row.id,
        "name": row.name,
        "code": row.code or "",
        "schedule_cron": row.schedule_cron,
        "enabled": bool(row.enabled),
        "created_at": created,
        "updated_at": updated,
    }


async def create_script(
    session: AsyncSession,
    user_id: str,
    *,
    name: str,
    code: str = "",
    schedule_cron: str | None = None,
    enabled: bool = True,
) -> StrategyScript:
    row = StrategyScript(
        user_id=user_id,
        name=name,
        code=code or "",
        schedule_cron=schedule_cron,
        enabled=bool(enabled),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_scripts(session: AsyncSession, user_id: str) -> list[StrategyScript]:
    result = await session.execute(
        select(StrategyScript)
        .where(StrategyScript.user_id == user_id)
        .order_by(StrategyScript.created_at.desc())
    )
    return list(result.scalars().all())


async def get_script(session: AsyncSession, user_id: str, script_id: str) -> StrategyScript | None:
    return await session.scalar(
        select(StrategyScript).where(
            StrategyScript.id == script_id, StrategyScript.user_id == user_id
        )
    )


async def update_script(
    session: AsyncSession,
    user_id: str,
    script_id: str,
    **fields: Any,
) -> StrategyScript | None:
    row = await get_script(session, user_id, script_id)
    if row is None:
        return None
    if "name" in fields and fields["name"] is not None:
        row.name = fields["name"]
    if "code" in fields and fields["code"] is not None:
        row.code = fields["code"]
    if "schedule_cron" in fields:
        row.schedule_cron = fields["schedule_cron"]
    if "enabled" in fields and fields["enabled"] is not None:
        row.enabled = bool(fields["enabled"])
    await session.commit()
    await session.refresh(row)
    return row


async def delete_script(session: AsyncSession, user_id: str, script_id: str) -> bool:
    row = await get_script(session, user_id, script_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


# ---- Encrypted env --------------------------------------------------------


def _decrypt_env_blob(blob: str | None) -> dict[str, str]:
    """Decrypt the stored env blob. Corrupt/missing blobs degrade to {}."""
    if not blob:
        return {}
    try:
        payload = json.loads(decrypt_secret(blob))
    except Exception as exc:  # noqa: BLE001 - never break reads on bad ciphertext
        logger.warning(f"strategy env blob undecryptable, treating as empty: {exc}")
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(k): str(v) for k, v in payload.items() if isinstance(v, str)}


def validate_env_key(key: str) -> str:
    """Return the stripped key or raise ValueError (router maps to 422)."""
    cleaned = (key or "").strip()
    if not cleaned or len(cleaned) > MAX_KEY_LEN or not KEY_RE.match(cleaned):
        raise ValueError(f"Invalid env key '{key}': must match [A-Za-z_][A-Za-z0-9_]* (<=64 chars)")
    return cleaned


async def get_env_keys(session: AsyncSession, user_id: str, script_id: str) -> list[str] | None:
    """Sorted set-key NAMES only. None when the script does not exist."""
    row = await get_script(session, user_id, script_id)
    if row is None:
        return None
    return sorted(_decrypt_env_blob(row.env_encrypted))


async def get_env_values(session: AsyncSession, user_id: str, script_id: str) -> dict[str, str] | None:
    """Full decrypted env map. Server-side only — never return via API."""
    row = await get_script(session, user_id, script_id)
    if row is None:
        return None
    return _decrypt_env_blob(row.env_encrypted)


async def merge_env(
    session: AsyncSession,
    user_id: str,
    script_id: str,
    updates: dict[str, Any],
) -> tuple[list[str], list[str]] | None:
    """Merge ``updates`` into the stored env. ``None`` values delete a key.

    Returns ``(sorted_all_keys, updated_keys)`` or None when missing script.
    Raises ValueError on invalid keys / oversized values (router maps to 422).
    """
    row = await get_script(session, user_id, script_id)
    if row is None:
        return None
    current = _decrypt_env_blob(row.env_encrypted)
    updated: list[str] = []
    for raw_key, raw_value in updates.items():
        key = validate_env_key(str(raw_key))
        if raw_value is None:
            current.pop(key, None)
            updated.append(key)
            continue
        if not isinstance(raw_value, str):
            raise ValueError(f"Env value for '{key}' must be a string")
        if len(raw_value) > MAX_VALUE_LEN:
            raise ValueError(f"Env value for '{key}' exceeds {MAX_VALUE_LEN} chars")
        if key not in current and len(current) >= MAX_KEYS:
            raise ValueError(f"Too many env vars (max {MAX_KEYS})")
        current[key] = raw_value
        updated.append(key)
    row.env_encrypted = encrypt_secret(json.dumps(current)) if current else None
    await session.commit()
    return sorted(current), sorted(updated)
