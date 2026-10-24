"""Company Research Agent.

Combines quote + fundamentals and produces an evidence-based research summary.
Explicitly instructs the model to separate facts from opinions and to flag
missing data.
"""

from __future__ import annotations

import json

from app.core.logging import get_logger
from app.services.agents.base import Agent, AgentContext, AgentResult, estimate_confidence
from app.services.data.service import market_data
from app.services.llm.gateway import gateway

logger = get_logger("agent.research")

SYSTEM_PROMPT = """You are a sell-side style research analyst. You are given a JSON object
with quote and fundamental data for a company. Write a SHORT research note (markdown)
covering: business snapshot, valuation metrics, financial health, and key risks.
Rules:
- Only state facts present in the data; where data is missing say so explicitly.
- Clearly separate factual data from your opinion.
- Do not give a price target; give a balanced qualitative view.
- End with an 'Evidence gaps' bullet list of what was unavailable."""


class ResearchAgent(Agent):
    name = "research"
    display_name = "Company Research"
    description = "Combines quote + fundamentals into a research note."

    async def run(self, ctx: AgentContext) -> AgentResult:
        quote = ctx.data.get("quote") or await market_data.get_quote(ctx.symbol, provider=ctx.provider)
        fundamentals = ctx.data.get("fundamentals") or await market_data.get_fundamentals(
            ctx.symbol, provider=ctx.provider
        )

        payload = {"symbol": ctx.symbol, "quote": quote, "fundamentals": fundamentals}

        try:
            text = await gateway.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, default=str)},
                ],
                provider=ctx.provider,
                temperature=0.3,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM unavailable for research agent: %s", exc)
            text = (
                f"Research snapshot for {ctx.symbol}: price {quote.get('price')} "
                f"({quote.get('currency')}), PE {fundamentals.get('trailingPE')}, "
                f"market cap {quote.get('market_cap')}. Full LLM analysis unavailable."
            )

        missing = sum(
            1
            for k in ("price", "name", "market_cap")
            if quote.get(k) is None
        )
        return AgentResult(
            content=text,
            data={"quote": quote, "fundamentals": fundamentals, "symbol": ctx.symbol},
            confidence=estimate_confidence(missing, 3),
            sources=[f"quote:{ctx.symbol}", f"fundamentals:{ctx.symbol}"],
            agent=self.name,
        )
