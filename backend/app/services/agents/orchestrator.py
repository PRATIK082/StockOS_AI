"""Agent Orchestrator.

Implements a lightweight Planner -> Executor -> Reviewer loop:

1. Planner picks which agents to run based on task intent.
2. Executor runs the chosen agents concurrently, each producing an AgentResult
   with evidence (data) and confidence.
3. Reviewer composes the final answer and an overall confidence from the
   individual agent results.

This is intentionally small for the first vertical slice; the interface is
structured so more agents plug in without changing the orchestrator.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger
from app.services.agents.base import AgentContext, AgentResult
from app.services.agents.chat import ChatAgent
from app.services.agents.research import ResearchAgent
from app.services.agents.technical import TechnicalAgent
from app.services.agents.fundamental import FundamentalAgent
from app.services.agents.momentum import MomentumAgent

logger = get_logger("orchestrator")

AGENTS: dict[str, Any] = {
    "technical": TechnicalAgent(),
    "research": ResearchAgent(),
    "chat": ChatAgent(),
    "fundamental": FundamentalAgent(),
    "momentum": MomentumAgent(),
}

# Simple keyword-based planner for the slice.
_INTENT_KEYWORDS = {
    "technical": ["technical", "indicator", "chart", "rsi", "macd", "support", "resistance", "bollinger", "ema", "sma"],
    "research": ["research", "analysis", "financial", "report", "compare", "overview"],
    "fundamental": ["fundamental", "valuation", "pe", "pb", "roe", "roce", "earnings", "revenue", "debt"],
    "momentum": ["momentum", "swing", "breakout", "trend", "volume", "scanner", "intraday"],
}


def _plan(intent: str | None, task: str) -> list[str]:
    task_l = task.lower()
    if intent == "technical":
        return ["technical"]
    if intent == "research":
        return ["research", "technical"]
    if intent == "chat":
        return ["chat"]

    score = {"technical": 0, "research": 0}
    for kind, kws in _INTENT_KEYWORDS.items():
        score[kind] = sum(1 for kw in kws if kw in task_l)
    if score["research"] > score["technical"] and score["research"] >= 1:
        return ["research", "technical"]
    if score["technical"] >= 1:
        return ["technical"]
    return ["chat"]


class Orchestrator:
    """Coordinates agents for a task and merges their outputs."""

    async def run(
        self,
        task: str,
        *,
        symbol: str | None = None,
        intent: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        if not task and not symbol:
            raise ValueError("A task description or symbol is required.")

        plan = _plan(intent, task)
        logger.info("Planner selected agents: %s", plan)

        ctx = AgentContext(task=task, symbol=symbol or "", provider=provider)

        async def _run(name: str):
            try:
                return await AGENTS[name].run(ctx)
            except Exception as exc:  # noqa: BLE001
                logger.exception("agent %s failed", name)
                return AgentResult(content=f"Agent '{name}' failed: {exc}", agent=name, confidence=0.1)

        results = await asyncio.gather(*[_run(name) for name in plan])

        sections = [{"agent": r.agent, "content": r.content, "confidence": r.confidence} for r in results]
        confidence = round(sum(r.confidence for r in results) / max(len(results), 1), 2)
        all_sources: list[str] = []
        for r in results:
            for s in r.sources:
                if s not in all_sources:
                    all_sources.append(s)

        combined = self._compose(plan, results)

        return {
            "task": task,
            "symbol": symbol or ctx.symbol,
            "plan": plan,
            "confidence": confidence,
            "sources": all_sources,
            "sections": sections,
            "answer": combined,
        }

    def _compose(self, plan: list[str], results) -> str:
        """Reviewer: assemble a single markdown answer from agent outputs."""
        parts: list[str] = []
        for r in results:
            parts.append(r.content)
        if len(parts) == 1:
            return parts[0]
        return "\n\n---\n\n".join(parts)


orchestrator = Orchestrator()
