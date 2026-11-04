"""Strategy Host runner (Phase 8): out-of-process script execution.

User code NEVER runs in the server process. Each run spawns a
``multiprocessing`` (spawn context — Windows-safe) child that ``exec``s the
script with a minimal ``ctx`` object:

- ``ctx.history(symbol, interval, period)`` — market data via the existing
  ``MarketDataService.get_history_auto`` facade. Failures degrade honestly to
  ``{"candles": [], "error": ...}`` — never fabricated.
- ``ctx.place_order(symbol, side, quantity, ...)`` — records an *intent* to a
  per-run JSONL file. Intents are filed by the PARENT (server) process, which
  honors ``REQUIRE_APPROVAL`` (files an ``ActionCenterItem`` pending, never
  fills) and otherwise uses the PAPER broker only in v1.
- ``ctx.log(...)`` — redacted line written to the per-run log (stdout/stderr
  from ``print`` are captured there too).

``__main__`` guard discipline: this module imports stdlib only at top level;
all ``app.*`` imports are deferred inside functions so a spawned child starts
fast and never executes server side effects at import. Test modules must
likewise keep import-time side effects to env setup + imports.

Per-run working dir: ``backend/data/strategy_runs/<run_id>/`` (``backend/data/``
is gitignored — runtime artifacts are never committed). Contents: ``script.py``
(code snapshot), ``log.txt`` (capped), ``orders.jsonl`` (intents),
``result.json`` (terminal status), ``meta.json`` (bookkeeping).

Log redaction: every secret VALUE from the script's stored env is replaced
with ``***`` before writing (child) and again on read (parent). Values
shorter than 4 chars are skipped to avoid nuking normal text.

Deterministic-tests hook: when the ``STRATEGY_HOST_HISTORY_STUB_JSON`` env
var is set (tests/local dev only), the child answers ``ctx.history`` from
that JSON instead of hitting providers — no network, fast suite. Unset in
production, where real market data is used.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 120.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 600.0
MAX_LOG_LINES = 2000
MAX_LOG_BYTES = 256 * 1024
REDACT_MIN_LEN = 4
REDACT_TOKEN = "***"

TERMINAL = ("completed", "failed", "killed", "stopped")


def runs_root() -> Path:
    """Per-run working dirs (lazily created; under gitignored backend/data/)."""
    root = Path(__file__).resolve().parents[3] / "data" / "strategy_runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def redact_text(text: str, secrets: list[str] | tuple[str, ...]) -> str:
    """Replace every stored secret VALUE with *** (canary-tested)."""
    out = text if isinstance(text, str) else str(text)
    for secret in secrets or []:
        if isinstance(secret, str) and len(secret) >= REDACT_MIN_LEN:
            out = out.replace(secret, REDACT_TOKEN)
    return out


class AlreadyRunning(RuntimeError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run already in progress: {run_id}")
        self.run_id = run_id


# ---- In-memory run registry (handles are process-local by nature) ----------

_RUNS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_meta(rec: dict[str, Any]) -> None:
    try:
        meta = {k: rec.get(k) for k in (
            "run_id", "script_id", "user_id", "status", "started_at",
            "ended_at", "timeout_seconds", "pid", "exitcode", "filed_intents",
        )}
        Path(rec["run_dir"], "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    except OSError:
        pass


def _snapshot(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": rec["run_id"],
        "script_id": rec["script_id"],
        "user_id": rec["user_id"],
        "status": rec["status"],
        "started_at": rec.get("started_at"),
        "ended_at": rec.get("ended_at"),
        "timeout_seconds": rec.get("timeout_seconds"),
        "pid": rec.get("pid"),
        "filed_intents": rec.get("filed_intents", 0),
    }


# ---- Spawned child ----------------------------------------------------------

def _child_main(payload: dict[str, Any]) -> None:
    """Worker entry point (runs in the spawned child ONLY)."""
    import asyncio
    import sys
    import traceback

    run_dir = str(payload.get("run_dir") or "")
    code = str(payload.get("code") or "")
    env = payload.get("env") or {}
    secrets = list(payload.get("secrets") or [])
    stub = payload.get("history_stub")
    if payload.get("database_url"):
        os.environ["DATABASE_URL"] = str(payload["database_url"])
    for key, value in (env.items() if isinstance(env, dict) else []):
        if isinstance(key, str) and isinstance(value, str) and key.isidentifier():
            os.environ[key] = value

    log_path = os.path.join(run_dir, "log.txt")
    intents_path = os.path.join(run_dir, "orders.jsonl")
    result_path = os.path.join(run_dir, "result.json")

    def _write_result(status: str, error: str | None) -> None:
        try:
            with open(result_path, "w", encoding="utf-8") as fh:
                json.dump({"status": status, "error": error}, fh)
        except OSError:
            pass

    try:
        fh = open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        _write_result("failed", "could not open run log")
        return

    sys.stdout = fh  # type: ignore[assignment]
    sys.stderr = fh  # type: ignore[assignment]
    written = [0]
    truncated_note = [False]

    def _emit(line: str) -> None:
        if truncated_note[0]:
            return
        try:
            fh.write(redact_text(line, secrets) + "\n")
            written[0] += len(line) + 1
        except (OSError, ValueError):
            return
        if written[0] > MAX_LOG_BYTES:
            try:
                fh.write("[strategy-host] log truncated (byte cap)\n")
            except (OSError, ValueError):
                pass
            truncated_note[0] = True

    class _Ctx:
        """Minimal script surface: history / place_order / log."""

        def log(self, *args: Any) -> None:
            _emit(" ".join(str(a) for a in args))

        def history(
            self, symbol: str, interval: str = "1d", period: str = "1y"
        ) -> dict[str, Any]:
            name = str(symbol or "").strip()
            if stub is not None:
                base = dict(stub) if isinstance(stub, dict) else {}
                base.setdefault("symbol", name)
                base.setdefault("candles", [])
                return base
            try:
                from app.services.data.service import market_data

                data = asyncio.run(
                    market_data.get_history_auto(
                        name, interval=str(interval or "1d"), period=str(period or "1y")
                    )
                )
                return data if isinstance(data, dict) else {"symbol": name, "candles": []}
            except Exception as exc:  # noqa: BLE001 - honest degradation
                return {
                    "symbol": name,
                    "interval": str(interval or "1d"),
                    "period": str(period or "1y"),
                    "candles": [],
                    "error": str(exc),
                }

        def place_order(
            self,
            symbol: str,
            side: str,
            quantity: Any = 1,
            price: Any = None,
            order_type: str = "MARKET",
        ) -> dict[str, Any]:
            sym = str(symbol or "").strip().upper()
            direction = str(side or "").strip().upper()
            try:
                qty = float(quantity)
            except (TypeError, ValueError):
                raise ValueError(f"place_order quantity must be numeric, got {quantity!r}") from None
            if not sym:
                raise ValueError("place_order requires a symbol")
            if direction not in ("BUY", "SELL"):
                raise ValueError(f"place_order side must be BUY|SELL, got {side!r}")
            if not qty > 0:
                raise ValueError(f"place_order quantity must be > 0, got {quantity!r}")
            intent = {
                "symbol": sym,
                "side": direction,
                "quantity": qty,
                "price": price,
                "order_type": str(order_type or "MARKET"),
            }
            try:
                with open(intents_path, "a", encoding="utf-8") as out:
                    out.write(json.dumps(intent) + "\n")
            except OSError as exc:
                raise ValueError(f"place_order could not record intent: {exc}") from None
            self.log(f"order queued: {direction} {qty:g} {sym}")
            return {"status": "queued", **intent}

    status, error = "completed", None
    try:
        gl: dict[str, Any] = {"ctx": _Ctx(), "__name__": "__main__"}
        exec(compile(code, "strategy.py", "exec"), gl)  # noqa: S102 - child process only
        main = gl.get("main")
        if callable(main):
            main(gl["ctx"])
    except SystemExit as exc:
        if exc.code not in (None, 0, ""):
            status, error = "failed", f"SystemExit({exc.code})"
    except Exception:  # noqa: BLE001 - traceback to the run log, honestly
        traceback.print_exc()
        tail = traceback.format_exc().strip().splitlines()
        status, error = "failed", tail[-1] if tail else "script error"
    _write_result(status, error)
    try:
        fh.close()
    except (OSError, ValueError):
        pass


# ---- Parent-side lifecycle ---------------------------------------------------

def _history_stub_from_env() -> dict[str, Any] | None:
    raw = os.environ.get("STRATEGY_HOST_HISTORY_STUB_JSON")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _terminate_locked(rec: dict[str, Any], reason: str) -> dict[str, Any]:
    """Kill the child for ``reason`` (killed|stopped). Caller holds _LOCK."""
    proc = rec.get("proc")
    if proc is not None and rec["status"] == "running":
        try:
            if proc.is_alive():
                proc.terminate()
        except (ValueError, OSError, AssertionError):
            pass
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                proc.join(timeout=0.2)
            except (ValueError, OSError, AssertionError):
                break
            if not proc.is_alive():
                break
        try:
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=2.0)
        except (ValueError, OSError, AssertionError):
            pass
        try:
            rec["exitcode"] = proc.exitcode
            proc.close()
        except (ValueError, OSError, AssertionError):
            pass
        rec["proc"] = None
    rec["status"] = reason
    rec["ended_at"] = _now_iso()
    try:
        Path(rec["run_dir"], "result.json").write_text(
            json.dumps({"status": reason, "error": None}), encoding="utf-8"
        )
    except OSError:
        pass
    _write_meta(rec)
    return _snapshot(rec)


def _watchdog(run_id: str, timeout: float) -> None:
    """Enforce the hard timeout even when nobody polls the run."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.2)
        with _LOCK:
            rec = _RUNS.get(run_id)
            if rec is None or rec["status"] != "running":
                return
    with _LOCK:
        rec = _RUNS.get(run_id)
        if rec is None or rec["status"] != "running":
            return
        _terminate_locked(rec, "killed")


def start_run(
    *,
    script_id: str,
    user_id: str,
    code: str,
    env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Spawn a worker for ``script_id``. Raises AlreadyRunning if live."""
    timeout = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)
    timeout = min(max(timeout, MIN_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS)
    with _LOCK:
        for rec in _RUNS.values():
            if (
                rec["script_id"] == script_id
                and rec["user_id"] == user_id
                and rec["status"] == "running"
            ):
                raise AlreadyRunning(rec["run_id"])
    run_id = uuid.uuid4().hex
    run_dir = runs_root() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "script.py").write_text(code or "", encoding="utf-8")
    (run_dir / "log.txt").write_text("", encoding="utf-8")
    env = dict(env or {})
    payload = {
        "run_dir": str(run_dir),
        "code": code or "",
        "env": env,
        "secrets": [v for v in env.values() if isinstance(v, str)],
        "history_stub": _history_stub_from_env(),
        "database_url": database_url or os.environ.get("DATABASE_URL", ""),
    }
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_child_main, args=(payload,), daemon=True)
    rec: dict[str, Any] = {
        "run_id": run_id,
        "script_id": script_id,
        "user_id": user_id,
        "status": "running",
        "started_at": _now_iso(),
        "ended_at": None,
        "timeout_seconds": timeout,
        "pid": None,
        "exitcode": None,
        "filed_intents": 0,
        "run_dir": str(run_dir),
        "proc": proc,
    }
    with _LOCK:
        _RUNS[run_id] = rec
    proc.start()
    with _LOCK:
        rec["pid"] = proc.pid
        _write_meta(rec)
    thread = threading.Thread(target=_watchdog, args=(run_id, timeout), daemon=True)
    thread.start()
    return _snapshot(rec)


def poll_run(run_id: str) -> dict[str, Any] | None:
    """Sync status refresh from process/result file. No I/O beyond the run dir."""
    with _LOCK:
        rec = _RUNS.get(run_id)
        if rec is None:
            return None
        if rec["status"] != "running":
            return _snapshot(rec)
        proc = rec.get("proc")
        alive = False
        if proc is not None:
            try:
                alive = proc.is_alive()
                if not alive:
                    rec["exitcode"] = proc.exitcode
                    proc.join(timeout=0)
                    proc.close()
                    rec["proc"] = None
            except (ValueError, OSError, AssertionError):
                alive = True
        if alive:
            return _snapshot(rec)
        # Child exited: adopt result.json (missing file = failed, honestly).
        try:
            result = json.loads(Path(rec["run_dir"], "result.json").read_text(encoding="utf-8"))
            status = str(result.get("status") or "")
        except (OSError, ValueError):
            status, result = "failed", {"status": "failed", "error": "missing result.json"}
        rec["status"] = status if status in TERMINAL else "failed"
        rec["ended_at"] = _now_iso()
        _write_meta(rec)
        return _snapshot(rec)


def stop_run(run_id: str) -> dict[str, Any] | None:
    """Kill a run. Returns {stopped, ...snapshot}; None when unknown."""
    with _LOCK:
        rec = _RUNS.get(run_id)
        if rec is None:
            return None
        if rec["status"] != "running":
            return {"stopped": False, **_snapshot(rec)}
        return {"stopped": True, **_terminate_locked(rec, "stopped")}


def _read_intent_lines(run_dir: str) -> list[dict[str, Any]]:
    path = Path(run_dir, "orders.jsonl")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    intents: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            intents.append(item)
    return intents


async def _file_intent(user_id: str, intent: dict[str, Any], run_dir: str) -> str:
    """File one place_order intent: approval-mode → Action Center pending,
    otherwise PAPER broker only (v1). Returns the outcome log line."""
    symbol = str(intent.get("symbol") or "").strip().upper()
    side = str(intent.get("side") or "").strip().upper()
    try:
        quantity = float(intent.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0.0
    if not symbol or side not in ("BUY", "SELL") or not quantity > 0:
        return f"[strategy-host] invalid order intent skipped: {intent!r}"[:300]

    from app.core.config import get_settings

    settings = get_settings()
    order_type = str(intent.get("order_type") or "MARKET")
    price: float | None = None
    try:
        if intent.get("price") is not None:
            price = float(intent["price"])
    except (TypeError, ValueError):
        price = None

    if settings.is_approval_required:
        from app.db.models.action_center import ActionCenterItem
        from app.db.session import SessionFactory

        async with SessionFactory() as session:
            item = ActionCenterItem(
                user_id=user_id,
                symbol=symbol,
                side=side,
                quantity=str(quantity),
                price=float(price) if price is not None else 0.0,
                status="pending",
                order_type=order_type,
                payload='{"kind": "strategy_host"}',
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            action_id = item.id
        return f"[strategy-host] order pending approval: {side} {quantity:g} {symbol} (action_center_id={action_id})"

    from decimal import Decimal

    from app.brokers.factory import get_broker
    from app.brokers.interface import BrokerSide, OrderType, ProductType

    broker = get_broker(name="paper", user_id=user_id)  # v1: paper ONLY
    try:
        result = await broker.place_order(
            symbol=symbol,
            side=BrokerSide(side),
            product=ProductType.CNC,
            order_type=OrderType(order_type),
            quantity=Decimal(str(quantity)),
            price=Decimal(str(price)) if price is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 - honest broker errors
        return f"[strategy-host] broker error for {side} {quantity:g} {symbol}: {exc}"[:300]
    if getattr(result, "status", None) in ("rejected", "cancelled"):
        note = getattr(result, "error_message", None) or "order rejected"
        return f"[strategy-host] order {result.status}: {side} {quantity:g} {symbol}: {note}"[:300]
    fill_price = float(result.filled_price) if getattr(result, "filled_price", None) else None
    try:
        from app.db.models.order import Order as OrderModel
        from app.db.session import SessionFactory

        async with SessionFactory() as session:
            session.add(OrderModel(
                user_id=user_id, symbol=symbol, side=side, quantity=str(quantity),
                price=fill_price or 0.0, status="filled",
                order_type=order_type,
                extra_data=getattr(result, "order_id", None),
            ))
            await session.commit()
    except Exception:  # noqa: BLE001 - fill stands even if bookkeeping fails
        pass
    try:
        from app.services.telegram import alerts as tg_alerts

        await tg_alerts.emit("order_filled", f"strategy_host {side} {quantity:g} {symbol}")
    except Exception:  # noqa: BLE001 - notifications never break fills
        pass
    return (
        f"[strategy-host] order filled (paper): {side} {quantity:g} {symbol}"
        f" @ {fill_price} (order_id={getattr(result, 'order_id', None)})"
    )


async def reap_run(run_id: str) -> dict[str, Any] | None:
    """Refresh status + file newly-recorded order intents (parent-side)."""
    snap = poll_run(run_id)
    if snap is None:
        return None
    with _LOCK:
        rec = _RUNS.get(run_id)
        if rec is None:
            return snap
        run_dir, user_id, filed = rec["run_dir"], rec["user_id"], int(rec.get("filed_intents", 0))
    intents = _read_intent_lines(run_dir)
    pending = intents[filed:]
    if not pending:
        return snap
    lines: list[str] = []
    done = filed
    for intent in pending:
        try:
            lines.append(await _file_intent(user_id, intent, run_dir))
            done += 1
        except Exception as exc:  # noqa: BLE001 - one bad intent never blocks the rest
            lines.append(f"[strategy-host] intent filing failed: {exc}"[:300])
            done += 1
    try:
        with open(Path(run_dir, "log.txt"), "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
    except OSError:
        pass
    with _LOCK:
        rec = _RUNS.get(run_id)
        if rec is not None:
            rec["filed_intents"] = done
            _write_meta(rec)
    return poll_run(run_id)


def read_logs(
    run_id: str, tail: int = 200, secrets: list[str] | None = None
) -> dict[str, Any] | None:
    """Last ``tail`` log lines (redacted). None when the run is unknown."""
    poll_run(run_id)
    with _LOCK:
        rec = _RUNS.get(run_id)
        snap = _snapshot(rec) if rec else None
        run_dir = rec["run_dir"] if rec else None
    if rec is None:
        # Post-restart: serve disk state (handles are process-local).
        meta_path = runs_root() / run_id / "meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            run_dir = str(runs_root() / run_id)
            snap = {
                "run_id": run_id,
                "script_id": meta.get("script_id"),
                "user_id": meta.get("user_id"),
                "status": meta.get("status", "unknown"),
                "started_at": meta.get("started_at"),
                "ended_at": meta.get("ended_at"),
                "timeout_seconds": meta.get("timeout_seconds"),
                "pid": meta.get("pid"),
                "filed_intents": meta.get("filed_intents", 0),
            }
        except (OSError, ValueError):
            return None
    tail = min(max(int(tail or 200), 1), MAX_LOG_LINES)
    try:
        lines = Path(run_dir, "log.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    kept = lines[-tail:]
    return {
        "run_id": run_id,
        "script_id": snap.get("script_id") if snap else None,
        "status": snap.get("status") if snap else "unknown",
        "logs": [redact_text(line, list(secrets or [])) for line in kept],
        "line_count": len(lines),
        "truncated": len(lines) > len(kept),
    }


def latest_run_for_script(user_id: str, script_id: str) -> dict[str, Any] | None:
    """Latest run snapshot for a script: registry first, disk scan fallback."""
    best: dict[str, Any] | None = None
    with _LOCK:
        for rec in _RUNS.values():
            if rec["user_id"] == user_id and rec["script_id"] == script_id:
                if best is None or str(rec["started_at"]) > str(best["started_at"]):
                    best = _snapshot(rec)
    if best is not None:
        return best
    try:
        root = runs_root()
    except OSError:
        return None
    for meta_path in root.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("user_id") != user_id or meta.get("script_id") != script_id:
            continue
        if best is None or str(meta.get("started_at")) > str(best.get("started_at", "")):
            best = {
                "run_id": meta_path.parent.name,
                "script_id": script_id,
                "user_id": user_id,
                "status": meta.get("status", "unknown"),
                "started_at": meta.get("started_at"),
                "ended_at": meta.get("ended_at"),
                "timeout_seconds": meta.get("timeout_seconds"),
                "pid": meta.get("pid"),
                "filed_intents": meta.get("filed_intents", 0),
            }
    return best


# ---- Scheduler seam ----------------------------------------------------------
# The scheduled-runs service (ScheduledResearchService) owns cron parsing
# (app.services.scheduler.cron) + due bookkeeping. Strategies piggyback on it
# via a {"kind": "strategy_host"} playbook — the same bridge approach as flow
# (flow_playbook()/run_playbook() in services/flow/executor.py).

def strategy_playbook(script_id: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Build a scheduled_research playbook dict referencing a strategy script.

    Parent wiring: ``ScheduledResearchService.create(user_id, name,
    playbook=strategy_playbook(sid), cron_expr="<script.schedule_cron>")``
    then a cron loop calls ``run_playbook`` on due tasks and ``mark_run``
    afterwards. See FINAL REPORT for exact wiring instructions.
    """
    return {"kind": "strategy_host", "script_id": script_id, "timeout_seconds": timeout_seconds}


async def run_playbook(playbook: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Run a ``{"kind": "strategy_host"}`` playbook for the scheduler loop.

    Honors ``enabled`` (disabled scripts are skipped, never executed) and
    paper-only v1 semantics (intents always file via the paper broker path;
    REQUIRE_APPROVAL files Action Center items instead of fills). Blocks until
    the worker reaches a terminal state or the timeout elapses (caller should
    run this in a worker thread if the cron loop must stay responsive).
    """
    import asyncio

    from app.core.config import get_settings
    from app.db.session import SessionFactory
    from app.services.strategy_host import store as strategy_store

    script_id = (playbook or {}).get("script_id")
    timeout = float((playbook or {}).get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    if not script_id:
        return {"kind": "strategy_host", "status": "error", "notes": ["playbook missing script_id"]}
    async with SessionFactory() as session:
        row = await strategy_store.get_script(session, user_id, str(script_id))
        if row is None:
            return {"kind": "strategy_host", "status": "error",
                    "notes": [f"script {script_id} not found"]}
        if not row.enabled:
            return {"kind": "strategy_host", "script_id": str(script_id),
                    "status": "skipped", "notes": ["script is disabled"]}
        code, script_name = row.code or "", row.name
        env = await strategy_store.get_env_values(session, user_id, str(script_id)) or {}
    try:
        snap = start_run(
            script_id=str(script_id), user_id=user_id, code=code, env=env,
            timeout_seconds=timeout, database_url=get_settings().database_url,
        )
    except AlreadyRunning as exc:
        return {"kind": "strategy_host", "script_id": str(script_id),
                "status": "already_running", "run_id": exc.run_id}
    run_id = snap["run_id"]
    deadline = time.time() + timeout + 30.0
    final: dict[str, Any] | None = None
    while time.time() < deadline:
        final = await reap_run(run_id)
        if final is not None and final.get("status") in TERMINAL:
            break
        await asyncio.sleep(0.5)
    if final is None or final.get("status") not in TERMINAL:
        stop_run(run_id)
        final = poll_run(run_id) or final
    tail_lines: list[str] = []
    try:
        logged = read_logs(run_id, tail=20, secrets=list(env.values()))
        if logged:
            tail_lines = list(logged.get("logs") or [])
    except (OSError, ValueError):
        pass
    return {
        "kind": "strategy_host",
        "script_id": str(script_id),
        "script_name": script_name,
        "run_id": run_id,
        "status": (final or {}).get("status", "unknown"),
        "logs_tail": tail_lines,
    }
