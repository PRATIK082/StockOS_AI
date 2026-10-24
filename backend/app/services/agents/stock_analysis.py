"""Stock Analysis Agent.

The "AI Pro" analysis agent behind the Prediction page. It assembles the real
trading data for a symbol — quote, fundamentals, OHLCV candles, computed
technical indicators, per-symbol trading statistics (trading days, up/down day
counts, volume/volume-trend, ATR, 52-week range, volatility, cap class) and the
live options chain signals (call/put bias, max pain, IV skew, ATM IV, premium
put/call ratio, nearest expiry) — then asks the LLM to reason over that data
and produce a professional, actionable analysis:

- executive BUY / SELL / HOLD verdict with a short- and long-term view
- trend & momentum readout
- volume & market participation
- fundamental snapshot
- options market view (call/put) when a chain exists
- a concrete trading plan (entry, stop loss, targets, risk-reward)
- risks and watch-outs

Every number the model reasons with comes from the data payload — nothing is
fabricated. Fields the provider does not return are left out of the payload
entirely so the model cannot invent them. If the LLM is unavailable the agent
degrades to a deterministic, equally data-backed analysis.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.services.agents.base import Agent, AgentContext, AgentResult
from app.services.data.service import market_data
from app.services.indicators import latest_signals
from app.services.llm.gateway import gateway

logger = get_logger("agent.stock_analysis")

_OPTIONS_EXCHANGES = {"NSE", "BSE", "NSEFO", "BSEFO"}

SYSTEM_PROMPT = """You are a top-tier investment analyst ("AI Pro"). You are given a JSON object
containing REAL market data for a single symbol: quote, fundamentals, candles, technical
indicators, trading statistics and (when available) options chain signals.

Produce a professional markdown analysis with these sections:
1. **Executive Verdict** — a clear BUY / SELL / HOLD recommendation with a short-term
   and long-term view (e.g. "BUY for the short term, HOLD long term").
2. **Trend & Momentum** — interpret the moving averages, RSI, MACD and 52-week position.
3. **Volume & Participation** — what average volume, the recent volume trend and the
   up/down day distribution say about conviction behind the move.
4. **Fundamentals** — valuation (PE/PB), profitability (ROE/margins) and growth, if present.
5. **Options Market View** — call/put bias, max pain, IV skew and ATM IV: what option
   traders expect, and whether CALL or PUT strategies favour the reader. Only if options
   data is present.
6. **Trading Plan** — a concrete entry zone, stop loss, upside targets for both the short
   and long term, and a risk-reward estimate. Derive these ONLY from levels present in
   the data (ATR, 52-week range, support/resistance, scenario prices).
7. **Risks & Watch-outs** — what could invalidate the view.

Rules:
- Only state facts present in the payload. Where a metric is absent, say "not available"
  instead of guessing.
- Never invent prices, levels or percentages that are not in the data.
- Be conservative; do not promise profits. End with a short disclaimer that this is
  research, not financial advice.
- Keep it concise but complete — a senior analyst's desk note, not an essay."""


def _f(value: Any, digits: int = 2) -> Any:
    """Round a finite number for the payload, pass everything else through."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    return round(v, digits)


def _fetch_options(symbol: str) -> dict | None:
    """Return option chain signals for NSE/BSE symbols, else None.

    Live import keeps this agent importable when options modules are absent.
    """
    ex = symbol.split(":", 1)[0] if ":" in symbol else ""
    if ex not in _OPTIONS_EXCHANGES:
        return None
    try:
        from app.services.options.signals import options_signals_service

        return options_signals_service.signals(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("options signals unavailable for %s: %s", symbol, exc)
        return None


class StockAnalysisAgent(Agent):
    name = "stock_analysis"
    display_name = "Stock Analysis"
    description = "Full AI-Pro stock analysis over real trading + options data."

    async def run(self, ctx: AgentContext) -> AgentResult:
        symbol = ctx.symbol
        if not symbol:
            return AgentResult(
                content="Stock Analysis requires a symbol.",
                data={},
                confidence=0.1,
                agent=self.name,
            )

        payload = await self._gather(symbol, ctx)

        content = await self._analyze(symbol, payload)

        missing = sum(1 for k in ("quote", "history", "trading_stats") if not payload.get(k))
        confidence = round(0.3 + 0.7 * ((3 - missing) / 3), 2)

        return AgentResult(
            content=content,
            data=payload,
            confidence=confidence,
            sources=[
                f"quote:{symbol}",
                f"history:{payload.get('history_candles', 0)} candles",
                f"options:{symbol}",
            ],
            agent=self.name,
        )

    async def _gather(self, symbol: str, ctx: AgentContext) -> dict:
        """Assemble the full real-data payload for the LLM (or the fallback)."""
        provider = ctx.provider

        try:
            quote = ctx.data.get("quote") or await market_data.get_quote(symbol, provider=provider)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stock analysis quote failed for %s: %s", symbol, exc)
            quote = {}

        try:
            history = ctx.data.get("history") or await market_data.get_history(symbol, provider=provider)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stock analysis history failed for %s: %s", symbol, exc)
            history = {"candles": []}

        candles = history.get("candles") or []
        closes = [float(c["close"]) for c in candles if isinstance(c.get("close"), (int, float))]

        indicators: dict = {}
        if len(closes) >= 30:
            try:
                import pandas as pd

                indicators = latest_signals(pd.Series(closes, name="close"))
                indicators["support"] = _f(min(c["low"] for c in candles[-20:] if c.get("low") is not None))
                indicators["resistance"] = _f(max(c["high"] for c in candles[-20:] if c.get("high") is not None))
            except Exception as exc:  # noqa: BLE001
                logger.warning("indicator computation failed for %s: %s", symbol, exc)

        try:
            fundamentals = ctx.data.get("fundamentals") or await market_data.get_fundamentals(symbol, provider=provider)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stock analysis fundamentals failed for %s: %s", symbol, exc)
            fundamentals = {}

        base_fund = fundamentals.get("base") if isinstance(fundamentals, dict) else None
        if isinstance(base_fund, dict) and base_fund:
            fundamentals = {**fundamentals, **base_fund}

        options = ctx.data.get("options") or _fetch_options(symbol)

        stats = ctx.data.get("trading_stats") or {}
        prediction = ctx.data.get("prediction") or {}

        return {
            "symbol": symbol,
            "quote": quote,
            "fundamentals": fundamentals,
            "indicators": indicators,
            "trading_stats": stats,
            "options": options,
            "prediction": prediction,
            "history_candles": len(candles),
            "recent_closes": [_f(c) for c in closes[-10:]],
        }

    async def _analyze(self, symbol: str, payload: dict) -> str:
        """LLM analysis with a deterministic, data-backed fallback."""
        compact = {
            "symbol": payload["symbol"],
            "quote": payload.get("quote") or None,
            "fundamentals": payload.get("fundamentals") or None,
            "indicators": payload.get("indicators") or None,
            "trading_stats": payload.get("trading_stats") or None,
            "options": payload.get("options") or None,
            "prediction": payload.get("prediction") or None,
            "recent_closes": payload.get("recent_closes") or None,
        }
        try:
            text = await gateway.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(compact, default=str)[:16000],
                    },
                ],
                provider=None,
                temperature=0.3,
            )
            if text and text.strip():
                return text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM unavailable for stock analysis agent (%s): %s",
                type(exc).__name__,
                exc or "(no detail)",
            )

        return self._fallback(payload)

    @staticmethod
    def _fallback(payload: dict) -> str:
        """Deterministic analysis built only from the real data present."""
        symbol = payload["symbol"]
        quote = payload.get("quote") or {}
        stats = payload.get("trading_stats") or {}
        ind = payload.get("indicators") or {}
        pred = payload.get("prediction") or {}
        options = payload.get("options") or {}

        price = quote.get("price")
        name = quote.get("name") or symbol

        lines = [f"## Stock Analysis: {name} ({symbol})\n"]

        lines.append("**Executive Verdict:**")
        action = pred.get("action") or "HOLD"
        horizon = pred.get("horizon") or "Short-term"
        lines.append(f"- **{action}** · {horizon} view\n")

        lines.append("**Trend & Momentum:**")
        trend = ind.get("trend")
        rsi = ind.get("rsi_14")
        if trend and rsi is not None:
            lines.append(f"- Trend {trend}, RSI {rsi:.0f} (EMA9 {ind.get('ema_9')}, EMA21 {ind.get('ema_21')}).")
        if stats.get("range_52w_position") is not None:
            lines.append(
                f"- Price sits at {stats['range_52w_position']:.0%} of its 52-week range "
                f"({stats.get('low_52w')} – {stats.get('high_52w')})."
            )
        lines.append("")

        lines.append("**Volume & Participation:**")
        up, down = stats.get("up_days"), stats.get("down_days")
        if up is not None and down is not None:
            lines.append(f"- {up} up days vs {down} down days across {stats.get('trading_days')} sessions.")
        if stats.get("avg_volume"):
            lines.append(
                f"- Avg volume {int(stats['avg_volume']):,} shares/day; "
                f"last-week volume trend {stats.get('volume_trend', 0):.0%} of average."
            )
        if stats.get("atr_pct"):
            lines.append(f"- ATR {stats.get('atr')} ({stats['atr_pct']:.2%} of price); volatility {stats.get('volatility', 0):.1%}.")
        lines.append("")

        fund = payload.get("fundamentals") or {}
        if any(fund.get(k) is not None for k in ("trailingPE", "priceToBook", "returnOnEquity", "profitMargins")):
            lines.append("**Fundamentals:**")
            if fund.get("trailingPE") is not None:
                lines.append(f"- PE {fund.get('trailingPE'):.1f}" if isinstance(fund.get("trailingPE"), (int, float)) else f"- PE {fund.get('trailingPE')}")
            if fund.get("priceToBook") is not None:
                lines.append(f"- Price/Book {fund.get('priceToBook'):.2f}")
            if fund.get("returnOnEquity") is not None:
                lines.append(f"- ROE {fund.get('returnOnEquity'):.1%}")
            if fund.get("profitMargins") is not None:
                lines.append(f"- Profit margin {fund.get('profitMargins'):.1%}")
            lines.append("")

        if options:
            lines.append("**Options Market View:**")
            bias = options.get("bias") or "NEUTRAL"
            lines.append(f"- Option-traders' bias: **{bias}**")
            if options.get("max_pain") is not None:
                lines.append(f"- Max pain {options['max_pain']} vs spot {options.get('spot_price')}.")
            if options.get("iv_skew") is not None:
                lines.append(f"- IV skew (OTM puts − OTM calls): {options['iv_skew']:+}")
            if options.get("atm_iv") is not None:
                lines.append(f"- ATM IV {options['atm_iv']:.1%}" if options["atm_iv"] > 1 else f"- ATM IV {options['atm_iv']:.2%}")
            if options.get("premium_put_call") is not None:
                lines.append(f"- Premium put/call ratio {options['premium_put_call']:.2f}")
            rec = options.get("recommendation")
            if rec:
                lines.append(f"- {rec}")
            if options.get("expiry"):
                lines.append(f"- Nearest expiry: {options['expiry']}.")
            lines.append("")

        lines.append("**Trading Plan:**")
        if price is not None:
            if stats.get("atr"):
                stop = float(price) - 1.5 * float(stats["atr"])
                t1 = float(price) * 1.03
                lines.append(f"- Reference: last close {float(price):,.2f}; ATR {stats['atr']}.")
                lines.append(f"- Suggested stop (1.5×ATR): {stop:,.2f}; short-term target: {t1:,.2f}.")
            if pred.get("bull_case") and pred.get("bear_case"):
                lines.append(
                    f"- Model scenarios: bull {float(pred['bull_case']):,.2f} / base "
                    f"{float(pred.get('base_case') or price):,.2f} / bear {float(pred['bear_case']):,.2f}."
                )
        lines.append("")

        lines.append("**Risks & Watch-outs:**")
        if stats.get("cap_class") and stats["cap_class"] != "n/a":
            lines.append(f"- {stats['cap_class']}-cap exposure; size positions accordingly.")
        if stats.get("volume_trend") is not None and stats["volume_trend"] < 0.85:
            lines.append("- Thin recent volume: moves may lack conviction.")
        if stats.get("range_52w_position") is not None and stats["range_52w_position"] > 0.9:
            lines.append("- Price near 52-week highs — chase risk elevated.")
        lines.append("")

        lines.append("_AI-generated research for information only — not investment advice._")
        return "\n".join(lines)


stock_analysis_agent = StockAnalysisAgent()
