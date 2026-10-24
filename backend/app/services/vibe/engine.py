"""Vibe Trading Chat engine.

A Vibe-Trading-style agent pipeline that streams real StockOS data in stages:
symbol detection -> live quote -> technical indicators -> options view ->
AI prediction -> LLM verdict. Every stage carries evidence (real data) and
degrades honestly on failure — a stage is reported as skipped/errored, never
fabricated.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from app.core.logging import get_logger
from app.services.agents.chat import _detect_symbol
from app.services.data.service import market_data
from app.services.llm.gateway import gateway
from app.services.options.signals import OptionsSignalsService
from app.services.prediction.engine import PredictionEngine, Timeframe
from app.services.technical.indicators import TechnicalIndicators

logger = get_logger("vibe.chat")

# Stage order surfaced as the streaming pipeline rail in the chat UI.
STAGE_PLAN: list[tuple[str, str]] = [
    ("symbol", "Symbol"),
    ("quote", "Live quote"),
    ("technical", "Technical indicators"),
    ("options", "Options view"),
    ("prediction", "AI prediction"),
    ("answer", "Verdict"),
]

ANSWER_SYSTEM_PROMPT = """You are the Vibe Trading assistant, a fast research agent inside StockOS.
You are given REAL data captured live from the market service for a symbol: a quote, real
technical-indicator readings, a real options-market snapshot (when available) and a deterministic
AI price prediction with confidence. Write a concise, well-structured markdown verdict.

Rules:
- Base every claim on the provided data. Never invent prices, levels, or signals.
- Structure: **Verdict** (1-2 lines, BUY/SELL/HOLD leaning), then short sections for
  Technicals, Options (only if data present), and Prediction. Use a short bullet list.
- Clearly say when a piece of data was unavailable (e.g. no options chain for this symbol).
- Never present predictions as guarantees. Add one line: "Research only, not investment advice."
- Keep it under ~200 words. No preamble."""


def _stage(status: str, key: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "stage", "status": status, "key": key, "data": data or {}}


class VibeChatEngine:
    """Streams a real-data analysis pipeline for a chat message."""

    def __init__(self, market_service=None, prediction=None, signals=None) -> None:
        self.market_service = market_service or market_data
        self.prediction = prediction or PredictionEngine(market_service=self.market_service)
        self.signals = signals or OptionsSignalsService(market_service=self.market_service)

    # --- pipeline ----------------------------------------------------------------------------

    async def stream(
        self,
        message: str,
        *,
        provider: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the pipeline, yielding one event dict per stage plus a final answer."""
        yield {"type": "plan", "plan": [{"key": k, "label": v} for k, v in STAGE_PLAN]}

        symbol = _detect_symbol(message)
        symbol = await self._resolve_symbol(symbol, provider) if symbol else None
        yield _stage("done" if symbol else "skipped", "symbol", {"symbol": symbol})

        if not symbol:
            answer = await self._answer_without_data(message, provider)
            yield {"type": "answer", "data": {"answer": answer, "confidence": 0.3, "symbol": None, "sources": []}}
            return

        # 1. Live quote
        quote: dict[str, Any] = {}
        try:
            quote = await self.market_service.get_quote(symbol, provider=provider)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vibe quote failed for %s: %s", symbol, exc)
        yield _stage("done" if quote.get("price") else "error", "quote", {"quote": quote})

        # 2. Technical indicators (real, from the same data path as the charts)
        tech = await self._technical_stage(symbol, provider)
        yield _stage("done" if tech.get("latest") else "error", "technical", tech)

        # 3. Options view (NSE/BSE underlyings with a real chain only)
        options = await self._options_stage(symbol, provider)
        yield _stage("done" if options.get("bias") else "skipped", "options", options)

        # 4. AI prediction (deterministic engine over the real candles)
        prediction = await self._prediction_stage(symbol, provider)
        yield _stage("done" if prediction.get("current_price") else "error", "prediction", prediction)

        # 5. LLM verdict over the collected real data (deterministic fallback)
        answer, confidence = await self._answer_with_data(message, symbol, quote, tech, options, prediction, provider)
        yield {
            "type": "answer",
            "data": {
                "answer": answer,
                "confidence": confidence,
                "symbol": symbol,
                "sources": self._sources(quote, tech, options, prediction),
            },
        }

    # --- stages ------------------------------------------------------------------------------

    async def _technical_stage(self, symbol: str, provider: str | None) -> dict[str, Any]:
        try:
            history = await self.market_service.get_history_auto(symbol, interval="1d", period="3mo")
        except Exception as exc:  # noqa: BLE001
            logger.warning("vibe technical failed for %s: %s", symbol, exc)
            return {}
        candles = (history or {}).get("candles") or []
        if not candles:
            return {}
        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        vols = [float(c.get("volume") or 0) for c in candles]
        ind = TechnicalIndicators
        macd = ind.macd_series(closes)
        latest = {
            name: {"value": r.value, "signal": r.signal, "strength": r.strength}
            for name, r in ind.analyze_all({"close": closes, "high": highs, "low": lows, "volume": vols}).items()
        }
        return {
            "symbol": symbol,
            "last_close": round(closes[-1], 4),
            "rsi": ind.rsi_series(closes, 14)[-1],
            "macd": macd["macd"][-1],
            "macd_hist": macd["histogram"][-1],
            "atr": ind.atr(highs, lows, closes, 14),
            "vwap": ind.vwap(highs, lows, closes, vols),
            "latest": latest,
        }

    async def _options_stage(self, symbol: str, provider: str | None) -> dict[str, Any]:
        ex = symbol.split(":", 1)[0] if ":" in symbol else ""
        if ex not in {"NSE", "BSE", "NSEFO", "BSEFO"}:
            return {}
        try:
            signals = await self.signals.signals(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug("vibe options skipped for %s: %s", symbol, exc)
            return {}
        if not signals:
            return {}
        return {
            "bias": signals.get("bias"),
            "strategy": signals.get("strategy"),
            "recommendation": signals.get("recommendation"),
            "max_pain": signals.get("max_pain"),
            "iv_skew": signals.get("iv_skew"),
            "atm_iv": signals.get("atm_iv"),
            "premium_put_call": signals.get("premium_put_call"),
            "spot_price": signals.get("spot_price"),
            "expiry": signals.get("expiry"),
        }

    async def _prediction_stage(self, symbol: str, provider: str | None) -> dict[str, Any]:
        try:
            result = await self.prediction.predict(symbol, Timeframe.WEEK)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vibe prediction failed for %s: %s", symbol, exc)
            return {}
        return {
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "current_price": result.current_price,
            "predicted_price": result.predicted_price,
            "confidence": result.confidence,
            "expected_return": result.expected_return,
            "bear_case": result.bear_case,
            "base_case": result.base_case,
            "bull_case": result.bull_case,
            "action": result.action,
            "horizon": result.horizon,
            "factors": result.factors,
            "trading_stats": result.trading_stats,
            "reasoning": result.reasoning,
        }

    # --- symbol resolution -------------------------------------------------------------------

    async def _resolve_symbol(self, symbol: str | None, provider: str | None) -> str | None:
        """Confirm a candidate symbol resolves to a real quote; try NSE:/NYSE: for bare tickers."""
        if not symbol:
            return None
        candidates = [symbol]
        if ":" not in symbol:
            candidates.extend([f"NSE:{symbol}", f"NYSE:{symbol}"])
        for cand in candidates:
            try:
                quote = await self.market_service.get_quote(cand, provider=provider)
            except Exception:  # noqa: BLE001
                continue
            if quote and quote.get("price"):
                return cand
        return None

    # --- LLM verdict --------------------------------------------------------------------------

    @staticmethod
    def _sources(quote, tech, options, prediction) -> list[str]:
        sources: list[str] = []
        if quote.get("provider"):
            sources.append(f"live-quote:{quote['provider']}")
        if tech.get("symbol"):
            sources.append("technical:indicators")
        if options.get("bias"):
            sources.append("options:chain")
        if prediction.get("symbol"):
            sources.append("prediction:engine")
        return sources

    async def _answer_with_data(
        self,
        message: str,
        symbol: str,
        quote: dict[str, Any],
        tech: dict[str, Any],
        options: dict[str, Any],
        prediction: dict[str, Any],
        provider: str | None,
    ) -> tuple[str, float]:
        context = {
            "symbol": symbol,
            "quote": {k: quote.get(k) for k in ("name", "price", "day_change_pct", "currency", "market_cap", "sector")},
            "technical": {k: tech.get(k) for k in ("last_close", "rsi", "macd", "macd_hist", "atr", "vwap")},
            "options": options or None,
            "prediction": {
                "timeframe": prediction.get("timeframe"),
                "current_price": prediction.get("current_price"),
                "predicted_price": prediction.get("predicted_price"),
                "expected_return": prediction.get("expected_return"),
                "confidence": prediction.get("confidence"),
                "action": prediction.get("action"),
                "bull_case": prediction.get("bull_case"),
                "base_case": prediction.get("base_case"),
                "bear_case": prediction.get("bear_case"),
                "factors": prediction.get("factors"),
            },
        }
        prompt = (
            f"User question: {message}\n\n"
            f"Live StockOS data for {symbol}:\n{json.dumps(context, default=str)[:12000]}"
        )
        try:
            text = await gateway.chat(
                [
                    {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                provider=provider,
                temperature=0.4,
            )
            if text and text.strip():
                return text.strip(), float(prediction.get("confidence") or 0.6)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vibe LLM verdict failed for %s: %s", symbol, exc)
        return self._deterministic_verdict(symbol, quote, tech, options, prediction), float(
            prediction.get("confidence") or 0.5
        )

    @staticmethod
    def _deterministic_verdict(
        symbol: str,
        quote: dict[str, Any],
        tech: dict[str, Any],
        options: dict[str, Any],
        prediction: dict[str, Any],
    ) -> str:
        lines = [f"**Verdict — {symbol}**\n"]
        price = quote.get("price")
        if price:
            chg = quote.get("day_change_pct")
            lines.append(f"- Last {price} ({f'{chg:+.2f}%' if chg is not None else 'n/a'}) — live quote.")
        rsi = tech.get("rsi")
        if rsi is not None:
            zone = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
            lines.append(f"- RSI(14) {rsi:.1f} ({zone}).")
        if prediction.get("action"):
            lines.append(
                f"- Deterministic engine: **{prediction['action']}** over {prediction.get('timeframe', '1W')} "
                f"(confidence {prediction.get('confidence', 0):.0%})."
            )
        if options.get("bias"):
            lines.append(f"- Options bias: **{options['bias']}**.")
        lines.append("\n*Live data summary — LLM verdict was unavailable.*\n*Research only, not investment advice.*")
        return "\n".join(lines)

    async def _answer_without_data(self, message: str, provider: str | None) -> str:
        try:
            text = await gateway.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are the Vibe Trading assistant inside StockOS. No ticker was detected in the "
                            "message, so answer the general market question concisely in markdown. If the user "
                            "wants a specific stock analysed, suggest an EXCHANGE:TICKER symbol (e.g. NSE:RELIANCE "
                            "or NYSE:AAPL). Research only, not investment advice."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                provider=provider,
                temperature=0.4,
            )
            return text.strip()
        except Exception:  # noqa: BLE001
            return (
                "No ticker detected. Try asking about a specific symbol in **EXCHANGE:TICKER** form, "
                "e.g. *\"What is the outlook for NSE:RELIANCE?\"*"
            )


vibe_chat_engine = VibeChatEngine()
