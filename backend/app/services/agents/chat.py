"""Conversation Agent.

Natural-language interface. Attempts to detect a ticker symbol in the user's
question, pulls live context when one is found, and answers with the LLM.
"""

from __future__ import annotations

import asyncio
import json
import re

from app.core.logging import get_logger
from app.services.agents import attachments as attachment_store
from app.services.agents import skills as skill_packs
from app.services.agents import websearch
from app.services.agents.base import Agent, AgentContext, AgentResult
from app.services.data.service import market_data
from app.services.llm.gateway import gateway

logger = get_logger("agent.chat")

SYSTEM_PROMPT = """You are an AI investment research assistant.
You are given optional live market context for a symbol. Answer the user's question.
Rules:
- Base answers on the provided data first; general knowledge second.
- Clearly distinguish data-backed statements from general opinions.
- If the question involves a specific stock but no data was attached, say you
  could not fetch live data and still answer from general knowledge.
- Never present predictions as guarantees.
- Keep answers concise and well structured with markdown."""

# Heuristic ticker matcher: common exchange prefixes plus an ALL-CAPS token.
_TICKER_RE = re.compile(r"\b(NSE|BSE|NYSE|NASDAQ|AMEX):?([A-Z][A-Z0-9.\-]{1,9})\b", re.IGNORECASE)
_CAPS_RE = re.compile(r"\b([A-Z]{2,6})\b")


def _detect_symbol(question: str) -> str | None:
    m = _TICKER_RE.search(question)
    if m:
        ex, tick = m.group(1).upper(), m.group(2).upper()
        return f"{ex}:{tick}"
    # Fallback: a standalone uppercase token that isn't a common word.
    stop = {"AI", "I", "A", "AN", "THE", "BUY", "SELL", "IPO", "ETF", "GDP", "PE", "ROE", "RSI"}
    for tok in _CAPS_RE.findall(question):
        if tok not in stop:
            return tok
    return None


class ChatAgent(Agent):
    name = "chat"
    display_name = "Conversation"
    description = "Answers natural-language questions, pulling live data when possible."

    async def run(self, ctx: AgentContext) -> AgentResult:
        question = ctx.task
        symbol = ctx.symbol or _detect_symbol(question)
        context: dict = {}

        if symbol:
            try:
                quote = await market_data.get_quote(symbol, provider=ctx.provider)
                context["quote"] = quote
            except Exception as exc:  # noqa: BLE001
                logger.warning("chat agent could not fetch quote: %s", exc)
                context["quote_error"] = str(exc)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        if context:
            messages.append(
                {
                    "role": "system",
                    "content": "Live context:\n" + json.dumps(context, default=str)[:12000],
                }
            )
        extra_sources: list[str] = []
        # P5-c extras, all supplied via ctx.data by the route layer.
        for att in (ctx.data.get("attachments") or [])[:5]:
            text = str(att.get("text") or "")[: attachment_store.CHAT_CONTEXT_CAP]
            if text.strip():
                messages.append(
                    {
                        "role": "system",
                        "content": f"Attached file '{att.get('filename', '?')}':\n{text}",
                    }
                )
                extra_sources.append(f"attachment:{att.get('id', '?')}")
        skill_block = skill_packs.render(ctx.data.get("skills"))
        if skill_block:
            messages.append({"role": "system", "content": skill_block[:6000]})
            found, _ = skill_packs.resolve(ctx.data.get("skills"))
            extra_sources.extend(f"skill:{s.name}" for s in found)
        if ctx.data.get("websearch"):
            query = ctx.data.get("websearch_query") or question
            if websearch.websearch_enabled():
                try:
                    result = await asyncio.to_thread(websearch.search, str(query)[:300])
                    lines = [f"- {h['title']} ({h['url']})" + (f": {h['snippet']}" if h.get("snippet") else "")
                             for h in result.get("results", [])]
                    body = "\n".join(lines)[:4000] or "(no parseable results)"
                    messages.append(
                        {"role": "system",
                         "content": "Web results (DuckDuckGo — verify before acting, may be stale):\n" + body}
                    )
                    extra_sources.append("web-search")
                except Exception as exc:  # noqa: BLE001 - honest degradation
                    logger.warning("web search failed, continuing without it: %s", exc)
                    messages.append(
                        {"role": "system",
                         "content": f"(Web search was requested but unavailable: {exc})"}
                    )
        messages.append({"role": "user", "content": question})

        try:
            text = await gateway.chat(messages, provider=ctx.provider, temperature=0.4)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM unavailable for chat agent: %s", exc)
            text = (
                f"I couldn't reach the local LLM (provider={ctx.provider or 'default'}). "
                f"Live quote context available: {context.get('quote', {}).get('price') if context else None}."
            )

        return AgentResult(
            content=text,
            data={"symbol": symbol, "context": context},
            confidence=0.6 if context.get("quote") else 0.4,
            sources=(["live-quote"] if context.get("quote") else []) + extra_sources,
            agent=self.name,
        )
