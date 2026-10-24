"""Agent base classes and result types.

An agent combines data retrieval with an LLM reasoning step. Every agent
returns an `AgentResult` carrying structured data plus generated text, so the
orchestrator can present evidence alongside the answer (explainable AI).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger


@dataclass
class AgentContext:
    """What an agent is allowed to work with for a given task."""

    task: str = ""
    symbol: str = ""
    provider: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5  # 0..1, set from evidence coverage
    sources: list[str] = field(default_factory=list)
    agent: str = ""


class Agent(ABC):
    name: str = "agent"
    display_name: str = "Agent"
    description: str = ""

    def __init__(self) -> None:
        self.logger = get_logger(f"agent.{self.name}")

    @abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult:
        """Execute the agent's reasoning over the context data."""


def estimate_confidence(missing: int, total: int) -> float:
    """Confidence = fraction of expected evidence fields that were present."""
    if total <= 0:
        return 0.3
    return round(0.3 + 0.7 * ((total - missing) / total), 2)
