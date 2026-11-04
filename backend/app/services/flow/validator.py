"""Pure graph validator for Flow strategies (Phase 7).

``validate(graph)`` performs no I/O: it reports unknown node types, dangling
edges, cycles, missing required params, and live-order nodes that lack an
approval-safe configuration.
"""

from __future__ import annotations

from app.services.flow.schemas import (
    CONDITION_OPERATORS,
    INDICATOR_FUNCTIONS,
    NODE_TYPES,
    Finding,
    FlowGraph,
)


def _node_ids(graph: FlowGraph) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in graph.nodes:
        counts[node.id] = counts.get(node.id, 0) + 1
    return counts


def _has_cycle(graph: FlowGraph, valid_ids: set[str]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = {nid: [] for nid in valid_ids}
    for edge in graph.edges:
        if edge.from_node in valid_ids and edge.to_node in valid_ids:
            adjacency[edge.from_node].append(edge.to_node)
    cycles: list[list[str]] = []
    color: dict[str, int] = {}  # 0=unvisited, 1=in-stack, 2=done
    stack: list[str] = []

    def visit(node_id: str) -> None:
        color[node_id] = 1
        stack.append(node_id)
        for nxt in adjacency.get(node_id, []):
            state = color.get(nxt, 0)
            if state == 0:
                visit(nxt)
            elif state == 1:
                cycles.append(stack[stack.index(nxt):] + [nxt])
        stack.pop()
        color[node_id] = 2

    for nid in sorted(valid_ids):
        if color.get(nid, 0) == 0:
            visit(nid)
    return cycles


def _positive_number(value: object) -> bool:
    try:
        return float(value) > 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def validate(graph: FlowGraph) -> list[Finding]:
    """Validate a flow graph and return a list of findings (empty == valid)."""
    findings: list[Finding] = []
    counts = _node_ids(graph)
    for node_id, count in sorted(counts.items()):
        if count > 1:
            findings.append(
                Finding(code="duplicate_node", message=f"Duplicate node id '{node_id}'", node_id=node_id)
            )
    by_id = {node.id: node for node in graph.nodes}
    valid_ids = set(by_id)

    for node in graph.nodes:
        if node.type not in NODE_TYPES:
            findings.append(
                Finding(
                    code="unknown_type",
                    message=f"Unknown node type '{node.type}' (allowed: {sorted(NODE_TYPES)})",
                    node_id=node.id,
                )
            )

    for edge in graph.edges:
        if edge.from_node not in valid_ids:
            findings.append(
                Finding(
                    code="dangling_edge",
                    message=f"Edge from unknown node '{edge.from_node}'",
                )
            )
        if edge.to_node not in valid_ids:
            findings.append(
                Finding(
                    code="dangling_edge",
                    message=f"Edge to unknown node '{edge.to_node}'",
                )
            )

    for cycle in _has_cycle(graph, valid_ids):
        findings.append(
            Finding(code="cycle", message=f"Cycle detected: {' -> '.join(cycle)}")
        )

    for node in graph.nodes:
        params = node.params if isinstance(node.params, dict) else {}
        if node.type == "market_data":
            if not str(params.get("symbol") or "").strip():
                findings.append(
                    Finding(
                        code="missing_param",
                        message="market_data node requires params.symbol",
                        node_id=node.id,
                    )
                )
        elif node.type == "indicator":
            func = str(params.get("function") or "").strip().lower()
            if func not in INDICATOR_FUNCTIONS:
                findings.append(
                    Finding(
                        code="missing_param",
                        message=(
                            f"indicator node requires params.function "
                            f"in {sorted(INDICATOR_FUNCTIONS)}"
                        ),
                        node_id=node.id,
                    )
                )
            if "period" in params and not _positive_number(params.get("period")):
                findings.append(
                    Finding(
                        code="missing_param",
                        message="indicator params.period must be a positive number",
                        node_id=node.id,
                    )
                )
        elif node.type == "condition":
            operator = str(params.get("operator") or "").strip().lower()
            if operator not in CONDITION_OPERATORS:
                findings.append(
                    Finding(
                        code="missing_param",
                        message=(
                            "condition node requires params.operator "
                            f"in {sorted(CONDITION_OPERATORS)}"
                        ),
                        node_id=node.id,
                    )
                )
            elif operator in ("not",):
                if "input" not in params and "left" not in params:
                    findings.append(
                        Finding(
                            code="missing_param",
                            message="condition 'not' requires params.input (or params.left)",
                            node_id=node.id,
                        )
                    )
            else:
                if "left" not in params or "right" not in params:
                    findings.append(
                        Finding(
                            code="missing_param",
                            message="condition node requires params.left and params.right",
                            node_id=node.id,
                        )
                    )
        elif node.type == "order":
            if not str(params.get("symbol") or "").strip():
                findings.append(
                    Finding(
                        code="missing_param",
                        message="order node requires params.symbol",
                        node_id=node.id,
                    )
                )
            if str(params.get("side") or "").strip().upper() not in ("BUY", "SELL"):
                findings.append(
                    Finding(
                        code="missing_param",
                        message="order node requires params.side BUY|SELL",
                        node_id=node.id,
                    )
                )
            qty = params.get("quantity", params.get("qty"))
            if not _positive_number(qty):
                findings.append(
                    Finding(
                        code="missing_param",
                        message="order node requires a positive params.quantity",
                        node_id=node.id,
                    )
                )
            if bool(params.get("live", False)) and not bool(params.get("require_approval", False)):
                findings.append(
                    Finding(
                        code="approval_unsafe",
                        message=(
                            "live order node must set params.require_approval=true "
                            "or run while approval mode routes through Action Center"
                        ),
                        node_id=node.id,
                    )
                )

    return findings
