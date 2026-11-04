"""Pydantic graph model for the Flow Visual Strategy Builder (Phase 7).

Node types v1 (closed set): ``market_data``, ``indicator``, ``condition``,
``order``, ``notification``. ``FlowNode.type`` is a plain ``str`` so the pure
validator can report unknown types as findings; the router rejects unknown
types at the API boundary with 422.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NODE_TYPES: tuple[str, ...] = ("market_data", "indicator", "condition", "order", "notification")

INDICATOR_FUNCTIONS: tuple[str, ...] = ("sma", "ema", "rsi", "macd")

CONDITION_OPERATORS: tuple[str, ...] = ("gt", "lt", "gte", "lte", "eq", "neq", "and", "or", "not")

RUN_MODES: tuple[str, ...] = ("dry_run", "live")


class FlowNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=32)
    params: dict[str, Any] = Field(default_factory=dict)


class FlowEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from", min_length=1, max_length=64)
    to_node: str = Field(alias="to", min_length=1, max_length=64)


class FlowGraph(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)


class Finding(BaseModel):
    code: str
    message: str
    node_id: str | None = None


class StepResult(BaseModel):
    node_id: str
    type: str
    status: str
    output: Any | None = None
    note: str | None = None


class RunReport(BaseModel):
    mode: str
    status: str
    step_results: list[StepResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class GraphCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    graph: FlowGraph
    schedule_cron: str | None = Field(default=None, max_length=64)
    enabled: bool = True
    paper_only: bool = True


class GraphUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    graph: FlowGraph | None = None
    schedule_cron: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None
    paper_only: bool | None = None


class RunRequest(BaseModel):
    graph_id: str | None = None
    inline_graph: FlowGraph | None = None
    mode: Literal["dry_run", "live"] = "dry_run"
