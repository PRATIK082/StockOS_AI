"""S4 live-quote hub: poll MarketDataService, fan out ticks to WS subscribers.

Poll-based (no broker stream yet): one background loop polls the union of all
subscribed symbols every ``poll_interval_s`` via the ``market_data`` singleton
(which itself falls back across providers). Each poll stamps the quote with a
server-side ``ts`` and fans the tick out to every subscriber queue watching
that symbol. Queues are bounded; a slow consumer drops ticks (counted) rather
than blocking the loop. Failures for one symbol never break other symbols.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.services.data.service import market_data

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
MAX_SYMBOLS_PER_CONN = 20
QUEUE_SIZE = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class QuoteHub:
    """Process-wide quote poller + subscriber fan-out."""

    def __init__(self, poll_interval_s: float = POLL_INTERVAL_S) -> None:
        self._poll_interval_s = poll_interval_s
        self._latest: dict[str, dict] = {}
        self._last_error: dict[str, str] = {}
        self._subs: dict[asyncio.Queue, set[str]] = {}
        self._task: asyncio.Task | None = None
        self._dropped = 0

    # ------------------------------------------------------------ lifecycle
    def _ensure_loop(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        try:
            while self._subs:
                symbols = sorted({s for syms in self._subs.values() for s in syms})
                for symbol in symbols:
                    try:
                        quote = await market_data.get_quote(symbol)
                    except Exception as exc:  # noqa: BLE001 - one symbol must not break the loop
                        self._last_error[symbol] = str(exc)[:200]
                        continue
                    if not isinstance(quote, dict) or quote.get("price") is None:
                        self._last_error[symbol] = "empty quote (no price)"
                        continue
                    tick = {**quote, "ts": _now_iso()}
                    self._latest[symbol] = tick
                    self._last_error.pop(symbol, None)
                    self._fanout(symbol, tick)
                await asyncio.sleep(self._poll_interval_s)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - loop must never die loudly
            logger.exception("quote hub poll loop died")

    def _fanout(self, symbol: str, tick: dict) -> None:
        msg = {"type": "tick", "tick": tick}
        for queue, syms in list(self._subs.items()):
            if symbol not in syms:
                continue
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                self._dropped += 1

    # ---------------------------------------------------------- subscribe
    async def subscribe(self, symbols: list[str]) -> asyncio.Queue:
        """Register a subscriber queue for ``symbols``; starts the loop."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subs[queue] = set(symbols)
        self._ensure_loop()
        return queue

    async def update(self, queue: asyncio.Queue, symbols: list[str]) -> None:
        if queue in self._subs:
            self._subs[queue] = set(symbols)
            self._ensure_loop()

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subs.pop(queue, None)

    def symbols_of(self, queue: asyncio.Queue) -> list[str]:
        return sorted(self._subs.get(queue, set()))

    # ---------------------------------------------------------------- read
    def get_latest(self, symbols: list[str]) -> dict[str, dict | None]:
        return {s: self._latest.get(s) for s in symbols}

    def status(self) -> dict:
        symbols = sorted({s for syms in self._subs.values() for s in syms})
        return {
            "provider": "market_data",
            "mode": "poll",
            "poll_interval_s": self._poll_interval_s,
            "symbols": symbols,
            "symbol_count": len(symbols),
            "subscribers": len(self._subs),
            "latest_cached": len(self._latest),
            "dropped_ticks": self._dropped,
        }


hub = QuoteHub()
