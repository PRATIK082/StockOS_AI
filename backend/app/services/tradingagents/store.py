"""DB-backed persistence for the Trading Desk.

- Saves a user's provider credentials (API key Fernet-encrypted) and resolves
  them back into an ``LLMSelection`` for the engine.
- Persists each engine run (decision, signal, reports, node trace) and marks
  simulations.

All engine data stored here is the real engine output — never sample data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import ProviderCredential, TradingRun, TradingRunNode
from app.services.tradingagents.llm_port import LLMSelection, PROVIDERS

logger = get_logger("tradingagents.store")


# --- Credentials ------------------------------------------------------------------


async def save_credential(
    session: AsyncSession,
    *,
    user_id: str,
    provider: str,
    api_key: str = "",
    base_url: str | None = None,
    deep_model: str | None = None,
    quick_model: str | None = None,
    is_default: bool = False,
) -> dict[str, Any]:
    """Upsert one provider credential for a user (raw key is encrypted at rest)."""
    row = await session.scalar(
        select(ProviderCredential).where(
            ProviderCredential.user_id == user_id,
            ProviderCredential.provider == provider,
        )
    )
    encrypted = encrypt_secret(api_key) if api_key else None
    if row is None:
        row = ProviderCredential(
            user_id=user_id,
            provider=provider,
            api_key_encrypted=encrypted or "",
            base_url=base_url,
            deep_model=deep_model,
            quick_model=quick_model,
            is_default=is_default,
        )
        session.add(row)
    else:
        if encrypted is not None:
            row.api_key_encrypted = encrypted
        if base_url is not None:
            row.base_url = base_url
        if deep_model is not None:
            row.deep_model = deep_model
        if quick_model is not None:
            row.quick_model = quick_model
        if is_default:
            row.is_default = True
    if is_default:
        await session.execute(
            update(ProviderCredential)
            .where(
                ProviderCredential.user_id == user_id,
                ProviderCredential.provider == provider,
                ProviderCredential.id != row.id,
            )
            .values(is_default=False)
        )
    await session.commit()
    await session.refresh(row)
    return _credential_public(row)


async def list_credentials(session: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(ProviderCredential)
            .where(ProviderCredential.user_id == user_id)
            .order_by(ProviderCredential.created_at.desc())
        )
    ).all()
    return [_credential_public(r) for r in rows]


async def delete_credential(session: AsyncSession, user_id: str, credential_id: str) -> bool:
    row = await session.scalar(
        select(ProviderCredential).where(
            ProviderCredential.id == credential_id,
            ProviderCredential.user_id == user_id,
        )
    )
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def resolve_selection(
    session: AsyncSession,
    user_id: str,
    requested: LLMSelection | None,
    *,
    provider: str | None = None,
) -> LLMSelection:
    """Build the effective selection for a run.

    Precedence: explicit per-request selections (``requested``) > the user's
    saved credential for that provider > the app default (``ta_default_provider``).
    """
    provider = (requested.provider if requested else provider) or ""
    cred = None
    if provider:
        cred = await session.scalar(
            select(ProviderCredential).where(
                ProviderCredential.user_id == user_id,
                ProviderCredential.provider == provider,
            )
        )

    if requested is not None:
        sel = requested
        # Fill missing pieces from the saved credential when available.
        if cred is not None:
            if not sel.api_key:
                sel.api_key = decrypt_secret(cred.api_key_encrypted) if cred.api_key_encrypted else None
            if not sel.base_url:
                sel.base_url = cred.base_url
            if not sel.deep_model:
                sel.deep_model = cred.deep_model
            if not sel.quick_model:
                sel.quick_model = cred.quick_model
        return sel

    if cred is not None:
        return LLMSelection(
            provider=cred.provider,
            deep_model=cred.deep_model,
            quick_model=cred.quick_model,
            api_key=decrypt_secret(cred.api_key_encrypted) if cred.api_key_encrypted else None,
            base_url=cred.base_url,
        )

    from app.core.config import settings

    default_provider = settings.llm_default_provider
    if default_provider not in PROVIDERS:
        default_provider = "ollama"
    return LLMSelection(provider=default_provider)


def _credential_public(row: ProviderCredential) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "is_default": row.is_default,
        "has_key": bool(row.api_key_encrypted),
        "base_url": row.base_url,
        "deep_model": row.deep_model,
        "quick_model": row.quick_model,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# --- Trading runs -----------------------------------------------------------------


async def create_run(
    session: AsyncSession,
    *,
    user_id: str,
    symbol: str,
    engine_symbol: str,
    trade_date: str,
    provider: str,
    deep_model: str,
    quick_model: str,
) -> TradingRun:
    row = TradingRun(
        user_id=user_id,
        symbol=symbol,
        engine_symbol=engine_symbol,
        trade_date=trade_date,
        provider=provider,
        deep_model=deep_model,
        quick_model=quick_model,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_run(
    session: AsyncSession,
    run_id: str,
    *,
    status: str | None = None,
    error: str | None = None,
    rating: str | None = None,
    signal: dict | None = None,
    final_decision: str | None = None,
    reports: dict[str, str] | None = None,
    node_trace: list[dict] | None = None,
    options: dict | None = None,
    simulated: bool | None = None,
) -> TradingRun | None:
    row = await session.scalar(select(TradingRun).where(TradingRun.id == run_id))
    if row is None:
        return None
    if status is not None:
        row.status = status
        if status in ("completed", "failed"):
            row.finished_at = datetime.now(timezone.utc)
    if error is not None:
        row.error = error
    if rating is not None:
        row.rating = rating
    if signal is not None:
        row.signal_json = json.dumps(signal, ensure_ascii=False)
    if final_decision is not None:
        row.final_decision = final_decision
    if reports is not None:
        row.reports_json = json.dumps(reports, ensure_ascii=False)
    if node_trace is not None:
        row.node_trace_json = json.dumps(node_trace, ensure_ascii=False)
    if options is not None:
        row.options_json = json.dumps(options, ensure_ascii=False)
    if simulated is not None:
        row.simulated = simulated
    await session.commit()
    await session.refresh(row)
    return row


async def add_run_nodes(session: AsyncSession, run_id: str, node_trace: list[dict]) -> None:
    for position, item in enumerate(node_trace):
        session.add(
            TradingRunNode(
                run_id=run_id,
                position=position,
                node=str(item.get("node") or ""),
                label=str(item.get("label") or ""),
                repeat=bool(item.get("repeat")),
            )
        )
    await session.commit()


async def get_run(session: AsyncSession, run_id: str, user_id: str) -> dict[str, Any] | None:
    row = await session.scalar(
        select(TradingRun).where(TradingRun.id == run_id, TradingRun.user_id == user_id)
    )
    if row is None:
        return None
    return _run_public(row)


async def list_runs(session: AsyncSession, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(TradingRun)
            .where(TradingRun.user_id == user_id)
            .order_by(TradingRun.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_run_public(r) for r in rows]


async def delete_run(session: AsyncSession, run_id: str, user_id: str) -> bool:
    """Delete one of the user's runs (and its node trace)."""
    row = await session.scalar(
        select(TradingRun).where(TradingRun.id == run_id, TradingRun.user_id == user_id)
    )
    if row is None:
        return False
    await session.execute(delete(TradingRunNode).where(TradingRunNode.run_id == run_id))
    await session.delete(row)
    await session.commit()
    return True


def _run_public(row: TradingRun) -> dict[str, Any]:
    def _load(value: str | None) -> Any:
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None

    return {
        "id": row.id,
        "symbol": row.symbol,
        "engine_symbol": row.engine_symbol,
        "trade_date": row.trade_date,
        "provider": row.provider,
        "models": {"deep": row.deep_model, "quick": row.quick_model},
        "status": row.status,
        "error": row.error,
        "rating": row.rating,
        "signal": _load(row.signal_json),
        "final_decision": row.final_decision,
        "reports": _load(row.reports_json),
        "node_trace": _load(row.node_trace_json),
        "options": _load(row.options_json),
        "simulated": row.simulated,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
