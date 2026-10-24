"""Trading Desk routes: provider credentials, engine runs, live SSE stream, simulate."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.schemas import TradingAnalyzeRequest, TradingCredentialCreate, TradingSimulateRequest
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Holding
from app.db.session import SessionFactory, get_session
from app.services.data.providers import parse_symbol
from app.services.data.service import market_data
from app.services.tradingagents import store
from app.services.tradingagents.config_port import build_engine_config
from app.services.tradingagents.engine import TradingDeskEngine
from app.services.tradingagents.llm_port import (
    LLMSelection,
    PROVIDERS,
    public_provider_list,
    validate_selection,
)

router = APIRouter(prefix="/trading", tags=["trading"])

logger = get_logger("trading.router")

# --- live run streaming (SSE) --------------------------------------------------------------

_run_queues: dict[str, asyncio.Queue] = {}
_main_loop: asyncio.AbstractEventLoop | None = None


def _register_queue(run_id: str, queue: asyncio.Queue) -> None:
    global _main_loop
    _run_queues[run_id] = queue
    if _main_loop is None:
        try:
            _main_loop = asyncio.get_running_loop()
        except RuntimeError:
            _main_loop = None


def _push_event(run_id: str, event: dict) -> None:
    queue = _run_queues.get(run_id)
    if queue is None:
        return
    if _main_loop is not None:
        # on_step runs on the engine worker thread; hop back to the app loop.
        _main_loop.call_soon_threadsafe(queue.put_nowait, event)
    else:
        try:
            queue.put_nowait(event)
        except RuntimeError:
            pass


def _pop_queue(run_id: str) -> None:
    _run_queues.pop(run_id, None)


# --- routes --------------------------------------------------------------------------------


@router.get("/providers")
async def providers(user: CurrentUser) -> dict:
    return {"default_provider": settings.ta_default_provider, "providers": public_provider_list()}


@router.get("/credentials")
async def credentials(user: CurrentUser, session: AsyncSession = Depends(get_session)) -> list[dict]:
    return await store.list_credentials(session, user.id)


@router.post("/credentials", status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: TradingCredentialCreate, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    if body.provider not in PROVIDERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown provider")
    return await store.save_credential(
        session,
        user_id=user.id,
        provider=body.provider,
        api_key=body.api_key,
        base_url=body.base_url,
        deep_model=body.deep_model,
        quick_model=body.quick_model,
        is_default=body.is_default,
    )


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_credential(
    credential_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> None:
    if not await store.delete_credential(session, user.id, credential_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credential not found")


async def _resolve_analyze(body: TradingAnalyzeRequest, user, session) -> tuple[LLMSelection, str]:
    symbol = (body.symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "symbol is required")
    try:
        parse_symbol(symbol)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid symbol '{symbol}': {exc}"
        ) from exc

    sel = LLMSelection(
        provider=body.provider or settings.ta_default_provider,
        deep_model=body.deep_model,
        quick_model=body.quick_model,
        api_key=body.api_key,
        base_url=body.base_url,
        temperature=body.temperature,
        llm_max_retries=body.llm_max_retries,
    )
    resolved = await store.resolve_selection(session, user.id, sel, provider=body.provider)
    errors = validate_selection(resolved)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(errors))
    return symbol, resolved


@router.post("/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze(
    body: TradingAnalyzeRequest, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    symbol, resolved = await _resolve_analyze(body, user, session)
    trade_date = body.trade_date or date.today().isoformat()
    option = None
    if body.option_type or body.option_strike is not None:
        option = {
            "type": (body.option_type or "CE").upper(),
            "strike": body.option_strike,
            "expiry": body.option_expiry,
        }

    async with SessionFactory() as session2:
        row = await store.create_run(
            session2,
            user_id=user.id,
            symbol=symbol,
            engine_symbol="",
            trade_date=trade_date,
            provider=resolved.provider,
            deep_model=resolved.deep_model or "",
            quick_model=resolved.quick_model or "",
        )
        run_id = row.id

    queue = asyncio.Queue(maxsize=500)
    _register_queue(run_id, queue)

    async def follow() -> None:
        try:
            await _execute_run(
                run_id=run_id,
                user_id=user.id,
                symbol=symbol,
                resolved=resolved,
                trade_date=trade_date,
                max_debate_rounds=body.max_debate_rounds,
                max_risk_rounds=body.max_risk_rounds,
                option=option,
            )
        finally:
            _push_event(run_id, {"done": True})
            _pop_queue(run_id)

    asyncio.create_task(follow())
    return {"run_id": run_id, "status": "running"}


async def _execute_run(
    *,
    run_id: str,
    user_id: str,
    symbol: str,
    resolved: LLMSelection,
    trade_date: str,
    max_debate_rounds: int | None,
    max_risk_rounds: int | None,
    option: dict | None = None,
) -> None:
    events: list[dict[str, str]] = []

    def on_step(node: str, label: str, _state: dict) -> None:
        step = {"node": node, "label": label}
        events.append(step)
        _push_event(run_id, step)

    try:
        config = await build_engine_config(
            resolved,
            max_debate_rounds=max_debate_rounds,
            max_risk_rounds=max_risk_rounds,
        )
        engine = TradingDeskEngine()
        result = await engine.run(
            symbol=symbol,
            sel=resolved,
            trade_date=trade_date,
            max_debate_rounds=max_debate_rounds,
            max_risk_rounds=max_risk_rounds,
            on_step=on_step,
            config=config,
        )
        node_trace = result["node_trace"]
        options = result.get("options")
        # A requested CE/PE contract (strike + type) gets a concrete leg view
        # appended to the same options payload: real Greeks from the provider
        # chain, with the premium driven off the engine's projected move.
        if option and option.get("strike") is not None:
            leg = await _trading_option_leg(symbol, option, result["signal"])
            if leg:
                options = dict(options) if options else {}
                options["available"] = True
                options["option_leg"] = leg
        async with SessionFactory() as session:
            updated = await store.update_run(
                session,
                run_id,
                status="completed",
                rating=result["rating"],
                signal=result["signal"],
                final_decision=result["final_decision"],
                reports=result["reports"],
                node_trace=node_trace,
                options=options,
            )
            await store.add_run_nodes(session, run_id, node_trace)
        _push_event(run_id, {"status": "completed", **(_public_run(updated) or {})})
    except Exception as exc:  # noqa: BLE001
        logger.error("Trading run %s failed: %s", run_id, exc)
        try:
            async with SessionFactory() as session:
                await store.update_run(session, run_id, status="failed", error=str(exc))
        except Exception:  # noqa: BLE001
            pass
        _push_event(run_id, {"status": "failed", "error": str(exc)})


async def _trading_option_leg(symbol: str, option: dict, signal) -> dict | None:
    """Append a concrete CE/PE contract view for a Trading Desk run.

    Re-uses the prediction engine's real-chain Greek + premium logic so the
    desk and the prediction pages compute the same (real) contract numbers.
    The projected underlying move is derived from the desk's own signal
    (direction × conviction), so the premium pricing never fights the verdict.
    """
    from app.services.prediction.engine import PredictionEngine

    direction = getattr(signal, "direction", "hold")
    conviction = float(getattr(signal, "conviction", 0.5) or 0.5)
    if direction in ("long", "buy"):
        expected_move = 0.0 + conviction * 0.04
    elif direction in ("short", "sell"):
        expected_move = 0.0 - conviction * 0.04
    else:
        expected_move = 0.0

    leg = await PredictionEngine(market_service=market_data)._build_option_leg(
        symbol,
        {},
        {"type": option.get("type"), "strike": option.get("strike"), "expiry": option.get("expiry")},
        underlying_return=expected_move,
    )
    if not leg:
        return None
    leg["driven_by"] = f"{getattr(signal, 'rating', 'Hold')} · {direction} @ {conviction:.0%}"
    return leg


def _public_run(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "symbol": row.symbol,
        "engine_symbol": row.engine_symbol,
        "trade_date": row.trade_date,
        "status": row.status,
    }


@router.get("/runs")
async def runs(user: CurrentUser, session: AsyncSession = Depends(get_session)) -> list[dict]:
    return await store.list_runs(session, user.id)


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    row = await store.get_run(session, run_id, user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return row


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_run(
    run_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> None:
    if not await store.delete_run(session, run_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    """SSE stream of live node/status events for a run."""
    row = await store.get_run(session, run_id, user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    async def event_stream() -> AsyncIterator[str]:
        queue = asyncio.Queue(maxsize=200)
        _register_queue(run_id, queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                if "done" in event:
                    break
        finally:
            _pop_queue(run_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _resolve_simulate_price(symbol: str) -> float | None:
    """Best-effort real price for a run symbol before giving up on the quote.

    Bare tickers (e.g. `TCS`) fail Yahoo's lookup alone — the desk's input is
    often a bare name, so we try the stockOS-qualified variant(s) as well.
    Returns the first real, positive number found.
    """
    candidates = [symbol]
    ex, _ = parse_symbol(symbol)
    if not ex:
        candidates.extend([f"NSE:{symbol}", f"NYSE:{symbol}"])
    for cand in candidates:
        try:
            quote = await market_data.get_quote(cand)
            price = quote.get("price")
            if price:
                return float(price)
        except Exception:  # noqa: BLE001
            continue
    return None


def _signal_or_option_price(run: dict) -> float | None:
    """Honest fallback price: the desk's signal target, else the theo premium."""
    signal = run.get("signal") or {}
    target = signal.get("price_target")
    if target:
        return float(target)
    options = run.get("options") or {}
    leg = options.get("option_leg") if isinstance(options, dict) else None
    if isinstance(leg, dict):
        premium = leg.get("current_premium")
        if premium:
            return float(premium)
    return None


@router.post("/runs/{run_id}/simulate", status_code=status.HTTP_201_CREATED)
async def simulate(
    run_id: str, body: TradingSimulateRequest, user: CurrentUser, session: AsyncSession = Depends(get_session)
) -> dict:
    run = await store.get_run(session, run_id, user.id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if run["status"] != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Run is not completed yet")
    if not run["symbol"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Run has no symbol")

    average = body.average_cost
    if average is None:
        average = await _resolve_simulate_price(run["symbol"])
        if average is None:
            # Honest fallbacks before giving up: the desk's own price target or
            # the theo premium of a requested CE/PE contract (both real data).
            average = _signal_or_option_price(run)
    if not average:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Could not resolve a current price; pass average_cost explicitly",
        )

    from decimal import Decimal

    existing = await session.scalar(
        select(Holding).where(Holding.user_id == user.id, Holding.symbol == run["symbol"])
    )
    if existing is None:
        existing = Holding(user_id=user.id, symbol=run["symbol"])
        session.add(existing)

    old_qty = Decimal(existing.quantity or "0")
    old_cost = Decimal(existing.average_cost or "0")
    new_qty = Decimal(str(body.quantity))
    new_cost = Decimal(str(round(float(average), 2)))

    total_qty = old_qty + new_qty
    if total_qty > 0:
        existing.average_cost = str((old_qty * old_cost + new_qty * new_cost) / total_qty)
    existing.quantity = str(total_qty)

    await session.commit()
    await session.refresh(existing)

    await store.update_run(session, run_id, simulated=True)
    return {
        "id": existing.id,
        "symbol": existing.symbol,
        "quantity": existing.quantity,
        "average_cost": existing.average_cost,
        "source_run": run_id,
    }