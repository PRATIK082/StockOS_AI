"""Background Trading Desk scheduler.

When ``ta_scheduler_enabled`` is on, the app lifespan starts this loop: every
``ta_scheduler_interval_minutes`` it re-analyses the symbols in every active
user's watchlist through the same engine+store pipeline the API uses, so the
desk keeps decisions fresh without manual runs (respecting per-user provider
credentials saved in the DB; Ollama default when none).

Real data only: runs write honest results (or honest failures) to ``trading_runs``.
"""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import User, Watchlist
from app.db.session import SessionFactory
from app.services.tradingagents.config_port import build_engine_config
from app.services.tradingagents.engine import TradingDeskEngine
from app.services.tradingagents.llm_port import validate_selection
from app.services.tradingagents.store import create_run, resolve_selection, update_run, add_run_nodes

logger = get_logger("tradingagents.scheduler")

MAX_SYMBOLS_PER_TURN = 5
_MIN_INTERVAL_SECONDS = 60
_MAX_SYMBOLS_PER_USER = 3


def _split_symbols(raw: str) -> list[str]:
    symbols = [s.strip().upper() for s in (raw or "").replace("\n", ",").split(",") if s.strip()]
    return [s for s in symbols if ":" in s]


class TradingScheduler:
    def __init__(self, interval_minutes: int | None = None):
        interval = interval_minutes if interval_minutes and interval_minutes > 0 else (
            settings.ta_scheduler_interval_minutes or 30
        )
        self.interval_seconds = max(interval * 60, _MIN_INTERVAL_SECONDS)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="trading-scheduler")
        logger.info("Trading scheduler started (interval %ss)", self.interval_seconds)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Trading scheduler stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._run_turn()
            except Exception:  # noqa: BLE001
                logger.exception("Trading scheduler turn failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _run_turn(self) -> None:
        logger.info("Trading scheduler turn: scanning watchlists")
        async with SessionFactory() as session:
            users = (await session.scalars(select(User).where(User.is_active == True))).all()  # noqa: E712
            targets: list[tuple[str, str]] = []
            for user in users:
                rows = (
                    await session.scalars(select(Watchlist).where(Watchlist.user_id == user.id))
                ).all()
                symbols: list[str] = []
                for row in rows[:1]:  # primary watchlist per user
                    symbols.extend(_split_symbols(row.symbols))
                # Dedupe preserving order; cap per user.
                seen: set[str] = set()
                for s in symbols:
                    if s not in seen:
                        seen.add(s)
                targets.extend((user.id, s) for s in list(seen)[:_MAX_SYMBOLS_PER_USER])
                if len(targets) >= MAX_SYMBOLS_PER_TURN:
                    break

            for user_id, symbol in targets:
                try:
                    await self._analyze(user_id, symbol)
                except Exception:  # noqa: BLE001
                    logger.warning("Scheduled analyse failed for %s: %s", symbol, exc_info=True)

    async def _analyze(self, user_id: str, symbol: str) -> None:
        """Analyse one symbol for one user, persisting the run."""
        trade_date = date.today().isoformat()
        async with SessionFactory() as session:
            sel = await resolve_selection(session, user_id, None)
            errors = validate_selection(sel)
            if errors:
                logger.info(
                    "Scheduler skip %s: provider not configured (%s)", symbol, "; ".join(errors)
                )
                return
            row = await create_run(
                session,
                user_id=user_id,
                symbol=symbol,
                engine_symbol="",
                trade_date=trade_date,
                provider=sel.provider,
                deep_model=sel.deep_model or "",
                quick_model=sel.quick_model or "",
            )
            run_id = row.id

        try:
            config = await build_engine_config(sel)
            engine = TradingDeskEngine()
            result = await engine.run(
                symbol=symbol, sel=sel, trade_date=trade_date, config=config
            )
            async with SessionFactory() as session:
                await update_run(
                    session,
                    run_id,
                    status="completed",
                    rating=result["rating"],
                    signal=result["signal"],
                    final_decision=result["final_decision"],
                    reports=result["reports"],
                    node_trace=result["node_trace"],
                )
                await add_run_nodes(session, run_id, result["node_trace"])
            logger.info("Scheduled run %s -> %s (%s)", symbol, result["rating"], run_id)
        except Exception as exc:  # noqa: BLE001
            async with SessionFactory() as session:
                await update_run(session, run_id, status="failed", error=str(exc))
            logger.warning("Scheduled run failed for %s: %s", symbol, exc)


# module-level singleton (wired in main.py lifespan)
_scheduler: TradingScheduler | None = None


def get_scheduler() -> TradingScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TradingScheduler()
    return _scheduler