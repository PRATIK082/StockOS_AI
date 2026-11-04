"""Broker plugin routes + admin diagnostics (Phase 9e).

Secrets (API key/secret, TOTP seed) are Fernet-encrypted and write-only:
no endpoint ever returns them — diagnostics reports only stored Y/N flags
and the last auth-check outcome.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_role
from app.brokers.interface import BrokerConnectRequest
from app.brokers.plugin_loader import list_plugins, load_broker_class, load_plugin_metadata
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.broker_credential import BrokerCredential
from app.db.models.user import User
from app.db.session import get_session

router = APIRouter(prefix="/brokers", tags=["brokers"])

AdminUser = Annotated[User, Depends(require_role("admin"))]


class CredentialsIn(BaseModel):
    api_key: str | None = Field(None, min_length=1, max_length=500)
    api_secret: str | None = Field(None, min_length=1, max_length=500)


class TotpSeedIn(BaseModel):
    seed: str = Field(min_length=1, max_length=256)


def _meta(name: str) -> dict[str, Any]:
    try:
        return load_plugin_metadata(name)
    except FileNotFoundError:
        raise HTTPException(404, f"Unknown broker plugin: {name}")


async def _cred_row(user_id: str, broker: str, session: AsyncSession) -> BrokerCredential | None:
    return (
        await session.execute(
            select(BrokerCredential).where(
                BrokerCredential.user_id == user_id, BrokerCredential.broker == broker
            )
        )
    ).scalar_one_or_none()


def _diagnostics_entry(meta: dict[str, Any], cred: BrokerCredential | None) -> dict[str, Any]:
    try:
        load_broker_class(meta["name"])
        loadable = True
    except Exception:  # noqa: BLE001
        loadable = False
    last_auth: dict[str, Any] | None = None
    if cred is not None and cred.last_auth_at is not None:
        last_auth = {"ok": cred.last_auth_ok, "at": cred.last_auth_at.isoformat()}
        if cred.last_auth_error:
            last_auth["error"] = cred.last_auth_error
    return {
        "name": meta["name"],
        "display_name": meta.get("display_name", meta["name"]),
        "broker_type": meta.get("broker_type"),
        "auth_required": bool(meta.get("auth_required", False)),
        "plugin_present": True,
        "class_loadable": loadable,
        "credentials_stored": bool(
            cred is not None and (cred.api_key_encrypted or cred.api_secret_encrypted)
        ),
        "totp_configured": bool(cred is not None and cred.totp_seed_encrypted),
        "last_auth": last_auth,
        "supported_exchanges": meta.get("supported_exchanges", []),
        "capabilities": meta.get("capabilities", []),
    }


@router.get("/plugins")
async def list_broker_plugins(user: CurrentUser) -> dict:
    return {"plugins": list_plugins()}


@router.get("/plugins/{name}/supports/{capability}")
async def supports(name: str, capability: str, user: CurrentUser) -> dict:
    try:
        return {"name": name, "capability": capability, "supported": _supports(name, capability)}
    except FileNotFoundError:
        return {"name": name, "capability": capability, "supported": False}


@router.get("/diagnostics")
async def diagnostics(
    user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Per-plugin diagnostics: presence, credential Y/N flags, last auth result."""
    out = []
    for meta in list_plugins():
        cred = await _cred_row(user.id, meta["name"], session)
        out.append(_diagnostics_entry(meta, cred))
    return {"brokers": out}


@router.post("/{name}/credentials", status_code=201)
async def save_credentials(
    name: str,
    body: CredentialsIn,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Store broker API credentials (write-only, Fernet-encrypted)."""
    _meta(name)
    if not body.api_key and not body.api_secret:
        raise HTTPException(422, "Provide api_key and/or api_secret")
    cred = await _cred_row(user.id, name, session)
    if cred is None:
        cred = BrokerCredential(user_id=user.id, broker=name)
        session.add(cred)
    if body.api_key:
        cred.api_key_encrypted = encrypt_secret(body.api_key)
    if body.api_secret:
        cred.api_secret_encrypted = encrypt_secret(body.api_secret)
    await session.commit()
    return {"name": name, "credentials_stored": True}


@router.post("/{name}/auth/verify")
async def verify_auth(
    name: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Credential check without trading: runs the broker handshake only.

    No order, quote, or funds call is made. The outcome is recorded for
    diagnostics; secrets are decrypted in memory and never returned.
    """
    meta = _meta(name)
    cred = await _cred_row(user.id, name, session)
    api_key = _decrypt(cred.api_key_encrypted) if cred else None
    api_secret = _decrypt(cred.api_secret_encrypted) if cred else None
    if meta.get("auth_required") and not (api_key or api_secret):
        raise HTTPException(409, "No credentials stored for this broker")
    try:
        from app.brokers.factory import get_broker

        broker = get_broker(name=name, user_id=user.id, session=session)
        connect = getattr(broker, "connect", None)
        if connect is None:
            raise AttributeError(f"Broker {name} has no connect() handshake")
        result = await connect(
            BrokerConnectRequest(api_key=api_key or "", api_secret=api_secret or "")
        )
        ok = bool(getattr(result, "authenticated", False))
        message = str(getattr(result, "message", ""))[:200]
        error = None if ok else (message or "Handshake not authenticated")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - verify must report, not crash
        ok, message, error = False, "", str(exc)[:200]
    if cred is None:
        cred = BrokerCredential(user_id=user.id, broker=name)
        session.add(cred)
    cred.last_auth_ok = ok
    cred.last_auth_at = datetime.utcnow()
    cred.last_auth_error = error
    await session.commit()
    return {"name": name, "authenticated": ok, "message": message,
            "last_auth_at": cred.last_auth_at.isoformat()}


@router.put("/{name}/totp-seed")
async def save_totp_seed(
    name: str,
    body: TotpSeedIn,
    user: AdminUser = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Store a broker TOTP seed (admin, write-only, Fernet-encrypted)."""
    _meta(name)
    seed = body.seed.strip().replace(" ", "").upper()
    try:
        base64.b32decode(seed, casefold=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Seed is not valid base32")
    cred = await _cred_row(user.id, name, session)
    if cred is None:
        cred = BrokerCredential(user_id=user.id, broker=name)
        session.add(cred)
    cred.totp_seed_encrypted = encrypt_secret(seed)
    await session.commit()
    return {"name": name, "totp_configured": True}


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return decrypt_secret(value)
    except Exception:  # noqa: BLE001
        return None


def _supports(name: str, capability: str) -> bool:
    from app.brokers.plugin_loader import plugin_supports

    return plugin_supports(name, capability)
