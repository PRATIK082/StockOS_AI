"""Flow graph executor (Phase 7).

``run_graph(graph, mode, user_id)`` executes nodes in topological order:

- ``market_data`` nodes fetch OHLCV via the existing market-data facade
  (``MarketDataService.get_history_auto``). Missing data degrades honestly to
  null outputs + notes — never fabricated.
- ``indicator`` nodes apply the existing functions in
  ``app.services.indicators`` (sma/ema/rsi/macd) over fetched closes.
- ``condition`` nodes evaluate a **whitelisted operator map only** — user
  params are data, never ``eval``-ed code.
- ``order`` nodes: ``dry_run`` only simulates; ``live`` with
  ``REQUIRE_APPROVAL`` execution mode files an ``ActionCenterItem`` and never
  fills directly; otherwise orders go through the broker (paper by default,
  forced paper when the graph is ``paper_only``).
- ``notification`` nodes call ``telegram.alerts.emit()`` when available,
  else log (``emit`` is a no-op without a configured bot and never raises).
"""

from __future__ import annotations

import operator as _operator
from decimal import Decimal
from typing import Any

from app.core.logging import get_logger
from app.services.flow.schemas import FlowGraph, RunReport, StepResult

logger = get_logger("flow.executor")

# Whitelisted condition operators ONLY — never eval() user input.
_OPERATORS = {
    "gt": _operator.gt,
    "lt": _operator.lt,
    "gte": _operator.ge,
    "lte": _operator.le,
    "eq": _operator.eq,
    "neq": _operator.ne,
    "and": lambda a, b: bool(a) and bool(b),
    "or": lambda a, b: bool(a) or bool(b),
    "not": lambda a, _b=None: not bool(a),
}


def _topo_order(graph: FlowGraph) -> list[str] | None:
    """Kahn's algorithm over valid edges; None when a cycle exists."""
    ids = [n.id for n in graph.nodes]
    known = set(ids)
    incoming: dict[str, int] = {nid: 0 for nid in ids}
    outgoing: dict[str, list[str]] = {nid: [] for nid in ids}
    for edge in graph.edges:
        if edge.from_node in known and edge.to_node in known:
            outgoing[edge.from_node].append(edge.to_node)
            incoming[edge.to_node] += 1
    queue = sorted(nid for nid in ids if incoming[nid] == 0)
    order: list[str] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for nxt in sorted(outgoing[nid]):
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
        queue.sort()
    return order if len(order) == len(ids) else None


def _scalar(value: Any) -> Any:
    """Unwrap a step output to a comparable scalar."""
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, dict):
        for key in ("value", "last_close", "price"):
            if key in value and isinstance(value[key], bool | int | float):
                return value[key]
        return None
    return None


def _closes_from_history(history: Any) -> list[float]:
    candles = []
    if isinstance(history, dict):
        candles = history.get("candles") or []
    closes: list[float] = []
    for candle in candles:
        if not isinstance(candle, dict):
            continue
        close = candle.get("close")
        try:
            if close is not None:
                closes.append(float(close))
        except (TypeError, ValueError):
            continue
    return closes


async def _run_market_data(node_id: str, params: dict[str, Any]) -> StepResult:
    from app.services.data.service import market_data

    symbol = str(params.get("symbol") or "").strip()
    interval = str(params.get("interval") or "1d")
    period = str(params.get("period") or "1y")
    if not symbol:
        return StepResult(node_id=node_id, type="market_data", status="error",
                          output=None, note="missing params.symbol")
    try:
        history = await market_data.get_history_auto(symbol, interval=interval, period=period)
    except Exception as exc:  # noqa: BLE001 - degrade honestly
        logger.warning(f"flow market_data {symbol} failed: {exc}")
        return StepResult(node_id=node_id, type="market_data", status="error",
                          output=None, note=f"market data unavailable for {symbol}: {exc}")
    closes = _closes_from_history(history)
    if not closes:
        err = (history or {}).get("error") if isinstance(history, dict) else None
        note = f"no market data for {symbol}" + (f": {err}" if err else "")
        return StepResult(node_id=node_id, type="market_data", status="empty",
                          output=None, note=note)
    return StepResult(
        node_id=node_id, type="market_data", status="ok",
        output={"symbol": symbol, "bars": len(closes), "closes": closes,
                "last_close": closes[-1]},
    )


def _resolve_input_name(node_id: str, params: dict[str, Any], graph: FlowGraph) -> str | None:
    if isinstance(params.get("input"), str) and params["input"]:
        return params["input"]
    for edge in graph.edges:
        if edge.to_node == node_id:
            return edge.from_node
    return None


def _run_indicator(
    node_id: str, params: dict[str, Any], context: dict[str, Any], graph: FlowGraph
) -> StepResult:
    import pandas as pd

    from app.services import indicators as ind

    func = str(params.get("function") or "").strip().lower()
    if func not in ("sma", "ema", "rsi", "macd"):
        return StepResult(node_id=node_id, type="indicator", status="error",
                          output=None, note=f"unsupported function '{func}'")
    source_name = _resolve_input_name(node_id, params, graph)
    closes: list[float] | None = None
    if source_name and isinstance(context.get(source_name), dict):
        maybe = context[source_name].get("closes")
        if isinstance(maybe, list) and maybe:
            closes = [float(c) for c in maybe]
    if not closes:
        for value in context.values():
            if isinstance(value, dict) and isinstance(value.get("closes"), list) and value["closes"]:
                closes = [float(c) for c in value["closes"]]
                break
    if not closes:
        return StepResult(node_id=node_id, type="indicator", status="empty",
                          output=None, note="no market data available for indicator")
    try:
        period = int(params.get("period", 14))
    except (TypeError, ValueError):
        period = 14
    series = pd.Series(closes, dtype=float)
    try:
        if func == "sma":
            out = ind.sma(series, period)
            value = out.dropna()
            result = None if value.empty else float(value.iloc[-1])
        elif func == "ema":
            out = ind.ema(series, period)
            value = out.dropna()
            result = None if value.empty else float(value.iloc[-1])
        elif func == "rsi":
            out = ind.rsi(series, period)
            value = out.dropna()
            result = None if value.empty else float(value.iloc[-1])
        else:  # macd
            fast = int(params.get("fast", 12))
            slow = int(params.get("slow", 26))
            signal = int(params.get("signal", 9))
            which = str(params.get("output", "macd")).lower()
            m_line, s_line, hist = ind.macd(series, fast, slow, signal)
            picked = {"macd": m_line, "signal": s_line, "hist": hist}.get(which, m_line)
            value = picked.dropna()
            result = None if value.empty else float(value.iloc[-1])
    except Exception as exc:  # noqa: BLE001
        return StepResult(node_id=node_id, type="indicator", status="error",
                          output=None, note=f"indicator failed: {exc}")
    if result is None:
        return StepResult(node_id=node_id, type="indicator", status="empty",
                          output=None, note="indicator produced no value (not enough bars)")
    return StepResult(node_id=node_id, type="indicator", status="ok",
                      output={"function": func, "value": result})


def _resolve_operand(operand: Any, context: dict[str, Any]) -> Any:
    if isinstance(operand, dict):
        if "node" in operand:
            return _scalar(context.get(operand["node"]))
        if "value" in operand:
            return operand["value"]
        return None
    if isinstance(operand, str) and operand in context:
        return _scalar(context[operand])
    return operand


def _run_condition(
    node_id: str, params: dict[str, Any], context: dict[str, Any]
) -> StepResult:
    operator_name = str(params.get("operator") or "").strip().lower()
    fn = _OPERATORS.get(operator_name)
    if fn is None:
        return StepResult(node_id=node_id, type="condition", status="error",
                          output=None, note=f"unsupported operator '{operator_name}'")
    if operator_name == "not":
        operand = params.get("input", params.get("left"))
        left = _resolve_operand(operand, context)
        if left is None:
            return StepResult(node_id=node_id, type="condition", status="empty",
                              output=None, note="condition input is null (missing upstream data)")
        try:
            return StepResult(node_id=node_id, type="condition", status="ok",
                              output=bool(fn(left)))
        except Exception as exc:  # noqa: BLE001
            return StepResult(node_id=node_id, type="condition", status="error",
                              output=None, note=f"condition failed: {exc}")
    left = _resolve_operand(params.get("left"), context)
    right = _resolve_operand(params.get("right"), context)
    if left is None or right is None:
        return StepResult(node_id=node_id, type="condition", status="empty",
                          output=None, note="condition operand is null (missing upstream data)")
    try:
        return StepResult(node_id=node_id, type="condition", status="ok",
                          output=bool(fn(left, right)))
    except Exception as exc:  # noqa: BLE001
        return StepResult(node_id=node_id, type="condition", status="error",
                          output=None, note=f"condition failed: {exc}")


def _upstream_conditions_pass(
    node_id: str, graph: FlowGraph, step_by_id: dict[str, StepResult]
) -> bool:
    for edge in graph.edges:
        if edge.to_node != node_id:
            continue
        prev = step_by_id.get(edge.from_node)
        if prev is not None and prev.type == "condition" and prev.output is False:
            return False
    return True


def _last_close_from_context(context: dict[str, Any]) -> float | None:
    for value in context.values():
        if isinstance(value, dict) and isinstance(value.get("last_close"), bool | int | float):
            return float(value["last_close"])
    for value in context.values():
        if isinstance(value, dict) and isinstance(value.get("value"), bool | int | float):
            return float(value["value"])
    return None


async def _run_order(
    node_id: str, params: dict[str, Any], context: dict[str, Any],
    graph: FlowGraph, step_by_id: dict[str, StepResult],
    *, mode: str, user_id: str, paper_only: bool,
) -> StepResult:
    symbol = str(params.get("symbol") or "").strip().upper()
    side = str(params.get("side") or "").strip().upper()
    try:
        quantity = float(params.get("quantity", params.get("qty", 0)))
    except (TypeError, ValueError):
        quantity = 0
    if not symbol or side not in ("BUY", "SELL") or quantity <= 0:
        return StepResult(node_id=node_id, type="order", status="error",
                          output=None, note="order requires symbol, side BUY|SELL, quantity > 0")
    if not _upstream_conditions_pass(node_id, graph, step_by_id):
        return StepResult(node_id=node_id, type="order", status="skipped",
                          output=None, note="skipped: upstream condition is false")

    if mode == "dry_run":
        return StepResult(
            node_id=node_id, type="order", status="simulated",
            output={"symbol": symbol, "side": side, "quantity": quantity,
                    "simulated_price": _last_close_from_context(context)},
            note="dry-run: no broker call, no fill",
        )

    # Live path.
    from app.core.config import get_settings

    settings = get_settings()
    if settings.is_approval_required:
        # Semi-auto: file for human approval, never fill directly.
        from app.db.models.action_center import ActionCenterItem
        from app.db.session import SessionFactory

        price = _last_close_from_context(context) or 0.0
        try:
            limit = params.get("price")
            if limit is not None:
                price = float(limit)
        except (TypeError, ValueError):
            pass
        async with SessionFactory() as session:
            item = ActionCenterItem(
                user_id=user_id,
                symbol=symbol,
                side=side,
                quantity=str(quantity),
                price=price,
                status="pending",
                order_type=str(params.get("order_type") or "MARKET"),
                payload=f'{{"kind": "flow", "node_id": "{node_id}"}}',
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            action_id = item.id
        return StepResult(
            node_id=node_id, type="order", status="pending_approval",
            output={"symbol": symbol, "side": side, "quantity": quantity,
                    "action_center_id": action_id},
            note="queued for approval in Action Center; no fill",
        )

    from app.brokers.factory import get_broker
    from app.brokers.interface import BrokerSide, OrderType, ProductType

    broker_name = "paper" if paper_only else (settings.selected_execution_broker or "paper")
    broker = get_broker(name=broker_name, user_id=user_id)
    try:
        result = await broker.place_order(
            symbol=symbol,
            side=BrokerSide(side),
            product=ProductType.CNC,
            order_type=OrderType(str(params.get("order_type") or "MARKET")),
            quantity=Decimal(str(quantity)),
            price=Decimal(str(params["price"])) if params.get("price") is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 - honest broker errors
        return StepResult(node_id=node_id, type="order", status="error",
                          output=None, note=f"broker error: {exc}")
    if getattr(result, "status", None) in ("rejected", "cancelled"):
        return StepResult(
            node_id=node_id, type="order", status=str(result.status),
            output={"symbol": symbol, "side": side, "quantity": quantity},
            note=getattr(result, "error_message", None) or "order rejected",
        )
    fill_price = float(result.filled_price) if getattr(result, "filled_price", None) else None
    # Persist the fill for traceability (mirrors the orders service).
    try:
        from app.db.models.order import Order as OrderModel
        from app.db.session import SessionFactory

        async with SessionFactory() as session:
            session.add(OrderModel(
                user_id=user_id, symbol=symbol, side=side, quantity=str(quantity),
                price=fill_price or 0.0, status="filled",
                order_type=str(params.get("order_type") or "MARKET"),
                extra_data=getattr(result, "order_id", None),
            ))
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - fill stands even if bookkeeping fails
        logger.warning(f"flow order bookkeeping failed: {exc}")
    try:
        from app.services.telegram import alerts as tg_alerts

        await tg_alerts.emit("order_filled", f"flow {side} {quantity} {symbol}")
    except Exception as exc:  # noqa: BLE001 - notifications never break fills
        logger.warning(f"flow fill alert failed: {exc}")
    return StepResult(
        node_id=node_id, type="order", status="filled",
        output={"symbol": symbol, "side": side, "quantity": quantity,
                "fill_price": fill_price, "order_id": getattr(result, "order_id", None)},
    )


async def _run_notification(node_id: str, params: dict[str, Any]) -> StepResult:
    message = str(params.get("message") or f"Flow alert from node {node_id}")
    sent = False
    note: str | None = "notification hook unavailable; logged only"
    try:
        from app.services.telegram import alerts as tg_alerts

        sent = bool(await tg_alerts.emit("flow", message))
        note = None if sent else "telegram bot unconfigured; logged only"
    except Exception as exc:  # noqa: BLE001
        note = f"notification failed (logged only): {exc}"
    logger.info(f"flow notification [{node_id}]: {message}")
    return StepResult(node_id=node_id, type="notification", status="done",
                      output={"sent": sent, "message": message}, note=note)


async def run_graph(
    graph: FlowGraph, mode: str, user_id: str, *, paper_only: bool = True
) -> RunReport:
    """Execute a flow graph. ``mode`` is ``dry_run`` or ``live``."""
    if mode not in ("dry_run", "live"):
        return RunReport(mode=mode, status="error", notes=[f"unknown mode '{mode}'"])
    order = _topo_order(graph)
    if order is None:
        return RunReport(mode=mode, status="blocked",
                         notes=["cycle detected: refusing to execute a cyclic graph"])
    by_id = {node.id: node for node in graph.nodes}
    context: dict[str, Any] = {}
    step_by_id: dict[str, StepResult] = {}
    steps: list[StepResult] = []
    for node_id in order:
        node = by_id[node_id]
        params = node.params if isinstance(node.params, dict) else {}
        if node.type == "market_data":
            step = await _run_market_data(node_id, params)
        elif node.type == "indicator":
            step = _run_indicator(node_id, params, context, graph)
        elif node.type == "condition":
            step = _run_condition(node_id, params, context)
        elif node.type == "order":
            step = await _run_order(node_id, params, context, graph, step_by_id,
                                    mode=mode, user_id=user_id, paper_only=paper_only)
        elif node.type == "notification":
            step = await _run_notification(node_id, params)
        else:
            step = StepResult(node_id=node_id, type=node.type, status="error",
                              output=None, note=f"unknown node type '{node.type}'")
        if step.output is None and node.type in ("market_data", "indicator", "condition"):
            context[node_id] = None
        else:
            context[node_id] = step.output
        step_by_id[node_id] = step
        steps.append(step)
    failed = [s.node_id for s in steps if s.status == "error"]
    status = "completed" if not failed else "completed_with_errors"
    return RunReport(mode=mode, status=status, step_results=steps,
                     notes=[f"failed nodes: {failed}"] if failed else [])


# ---- Scheduler seam -------------------------------------------------------
# The existing scheduled-runs service (ScheduledResearchService) owns cron
# parsing (app.services.scheduler.cron) and due-task bookkeeping. Flow graphs
# piggyback on it via a {"kind": "flow"} playbook instead of a new scheduler.

def flow_playbook(graph_id: str, mode: str = "dry_run") -> dict[str, Any]:
    """Build a scheduled_research playbook dict that references a flow graph.

    Parent wiring: ``ScheduledResearchService.create(user_id, name,
    playbook=flow_playbook(gid), cron_expr="0 9 * * *")`` then a cron loop
    calls ``run_playbook`` on due tasks and ``mark_run`` afterwards.
    """
    return {"kind": "flow", "graph_id": graph_id, "mode": mode}


async def run_playbook(playbook: dict[str, Any], user_id: str) -> RunReport:
    """Run a ``{"kind": "flow"}`` playbook for the scheduler loop."""
    from app.db.session import SessionFactory
    from app.services.flow import store as flow_store

    graph_id = (playbook or {}).get("graph_id")
    mode = (playbook or {}).get("mode", "dry_run")
    if not graph_id:
        return RunReport(mode=str(mode), status="error", notes=["playbook missing graph_id"])
    async with SessionFactory() as session:
        row = await flow_store.get_graph(session, user_id, str(graph_id))
        payload = flow_store.to_dict(row) if row else None
    if payload is None:
        return RunReport(mode=str(mode), status="error", notes=[f"graph {graph_id} not found"])
    if not payload.get("enabled", True):
        return RunReport(mode=str(mode), status="skipped", notes=["graph is disabled"])
    import json as _json

    definition = payload.get("definition") or {}
    if isinstance(definition, str):
        try:
            definition = _json.loads(definition)
        except (ValueError, TypeError):
            definition = {}
    try:
        flow_graph = FlowGraph.model_validate(definition)
    except Exception as exc:  # noqa: BLE001
        return RunReport(mode=str(mode), status="error", notes=[f"invalid graph definition: {exc}"])
    return await run_graph(flow_graph, str(mode), user_id,
                           paper_only=bool(payload.get("paper_only", True)))
