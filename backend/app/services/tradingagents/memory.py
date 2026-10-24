"""Local decision-log persistence for Trading Desk runs.

Writes one JSON record per completed engine run under the StockOS ``ta_data_root``
(``data/tradingagents/decisions/*.jsonl``). This is an append-only, crash-safe
log that the dashboard's "decision history" reads from; it complements the
vendored ``TradingMemoryLog`` (which owns past-context injection) and is
separate from the SQLAlchemy ``trading_runs`` table added in a later phase.

No fabricated outcomes: every record holds the engine's real decision text and
the deterministic signal derived from it.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.tradingagents.signal import TradingSignal, parse_trading_signal


class DecisionLog:
    """Append-only JSONL decision log under the StockOS data root."""

    def __init__(self, root: str | Path):
        self._root = Path(root).expanduser()
        self._dir = self._root / "decisions"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def log_path(self) -> Path:
        return self._dir / "trading_runs.jsonl"

    def record(
        self,
        *,
        symbol: str,
        engine_symbol: str,
        trade_date: str,
        provider: str,
        deep_model: str,
        quick_model: str,
        final_decision: str,
        rating: str,
        signal: TradingSignal | None = None,
        reports: dict[str, str] | None = None,
        node_trace: list[dict] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Append one run record. Returns the stored record (with timestamps)."""
        sig = signal if signal is not None else parse_trading_signal(final_decision, rating)
        record: dict[str, Any] = {
            "id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "symbol": symbol,
            "engine_symbol": engine_symbol,
            "trade_date": trade_date,
            "provider": provider,
            "models": {
                "deep": deep_model,
                "quick": quick_model,
            },
            "rating": rating,
            "signal": sig.to_dict(),
            "final_decision": final_decision,
            "reports": reports or {},
            "node_trace": node_trace or [],
            "error": error,
        }
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def read_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Read records newest-first."""
        if not self.log_path.exists():
            return []
        with self._lock:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        records = []
        for line in lines[-limit * 10:]:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(records[-limit:]))


# Convenience module-level log rooted at the StockOS data root.
def get_decision_log(root: str | Path | None = None) -> DecisionLog:
    if root is None:
        from app.core.config import settings
        root = settings.ta_data_root
    return DecisionLog(root)


_default_log: DecisionLog | None = None


def decision_log() -> DecisionLog:
    global _default_log
    if _default_log is None:
        _default_log = get_decision_log()
    return _default_log