"""Technical Analysis Agent.

Computes indicators from OHLCV data, then uses the LLM to produce a concise,
evidence-based technical readout.
"""

from __future__ import annotations

import json

from app.core.logging import get_logger
from app.services.agents.base import Agent, AgentContext, AgentResult, estimate_confidence
from app.services.data.service import market_data
from app.services.indicators import latest_signals
from app.services.llm.gateway import gateway

logger = get_logger("agent.technical")

SYSTEM_PROMPT = """You are a professional technical analyst. You are given a JSON object
with OHLCV candles and computed indicator signals. Produce a SHORT technical readout
(markdown) covering: trend bias, momentum (RSI), MACD stance, key support/resistance
(inferred from recent candles), and a one-line actionable view. Be conservative.
Never invent price levels not derivable from the given data."""


class TechnicalAgent(Agent):
    name = "technical"
    display_name = "Technical Analysis"
    description = "Computes indicators and produces a technical readout."

    async def run(self, ctx: AgentContext) -> AgentResult:
        history = ctx.data.get("history") or await market_data.get_history(
            ctx.symbol, provider=ctx.provider
        )
        candles = history.get("candles", [])
        if not candles:
            return AgentResult(
                content="No price history available for analysis.",
                data={"signals": {}, "history": {"candles": 0}},
                confidence=0.1,
                agent=self.name,
            )

        closes = [c["close"] for c in candles if c.get("close") is not None]
        import pandas as pd

        series = pd.Series(closes, name="close")
        signals = latest_signals(series)

        last_20 = candles[-20:]
        highs = [c["high"] for c in last_20 if c.get("high") is not None]
        lows = [c["low"] for c in last_20 if c.get("low") is not None]
        signals["support"] = round(min(lows), 4) if lows else None
        signals["resistance"] = round(max(highs), 4) if highs else None

        payload = {
            "symbol": ctx.symbol,
            "signals": signals,
            "candles_count": len(candles),
            "recent_closes": closes[-5:],
        }

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
            logger.warning("LLM unavailable for technical agent: %s", exc)
            text = (
                f"Indicator snapshot for {ctx.symbol}: RSI {signals['rsi_14']}, "
                f"trend {signals['trend']}, support {signals['support']}, "
                f"resistance {signals['resistance']}."
            )

        missing = sum(1 for k in ("rsi_14", "macd", "ema_50") if signals.get(k) is None)
        return AgentResult(
            content=text,
            data={"signals": signals, "symbol": ctx.symbol},
            confidence=estimate_confidence(missing, 3),
            sources=[f"history:{len(candles)} candles"],
            agent=self.name,
        )
