"""Deep multi-symbol Ask-AI analysis engine.

Runs a Vibe-style pipeline over a *selection* of symbols (multi-symbol deep
analysis): for each picked symbol it gathers the real StockOS feeds — live
quote, technical-indicator snapshot (now including Stochastic / Supertrend /
ADX-DMI / CCI / MFI / Williams %R / OBV / Parabolic SAR / Ichimoku), an
options-market view when the symbol has a real chain, and a deterministic AI
prediction. It then asks the LLM for one comparative verdict that answers the
user's free-form question using that evidence plus its own knowledge.

Streaming contract mirrors the Vibe chat engine so the frontend reuses the same
SSE reader:
- ``{"type": "plan", "plan": [{"key", "label"}...]}``
- ``{"type": "stage", "key": "<symbol>|<measure>", "status", "data"}``
- ``{"type": "answer", "data": {"answer", "confidence", "symbol", "sources"}}``

Everything degrades honestly: a stage that fails is emitted as ``error``; when
the LLM is unreachable a deterministic comparative summary is returned instead
of fabricating prose.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from app.core.logging import get_logger
from app.services.data.service import MarketDataService, market_data
from app.services.llm.gateway import gateway
from app.services.options.signals import OptionsSignalsService
from app.services.prediction.engine import PredictionEngine, Timeframe
from app.services.technical.indicators import TechnicalIndicators

logger = get_logger("deep.analysis")

ASYSTEM = """You are the StockOS Deep Analysis assistant — a senior multi-asset analyst with a
vast library of investment knowledge that you combine with the REAL live data provided for
each symbol (quote, technical indicators, options market view, AI prediction). The user
picked these symbols and asked a specific question.

Rules:
- Base every claim on the provided data. Use your knowledge for context (sector, macro,
  correlations, risk), but never invent prices, levels, order flows, or signals.
- If the user's question mentions a time frame you don't see data for, say which data
  you do have and reason from it.
- Compare the symbols against each other and directly answer the question first (1-2
  lines), then give a concise per-symbol breakdown as a markdown table or bullets, then
  3-5 clear takeaways/trades.
- Clearly say when data was unavailable for a symbol (no chain, no prediction, etc.).
- Never present predictions as guarantees. End with one line: "Research only, not investment advice."
- Keep it under ~450 words. Strong, specific, no filler."""


def _stage(status: str, key: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "stage", "status": status, "key": key, "data": data or {}}


class DeepAnalysisEngine:
    def __init__(
        self,
        market_service: MarketDataService | None = None,
        signals: OptionsSignalsService | None = None,
        prediction: PredictionEngine | None = None,
    ) -> None:
        self.market_service = market_service or market_data
        self.signals = signals or OptionsSignalsService(market_service=self.market_service)
        self.prediction = prediction or PredictionEngine(market_service=self.market_service)

    # --- public API -------------------------------------------------------------------------

    async def stream(self, body: Any) -> AsyncIterator[dict[str, Any]]:
        symbols = await self._resolve(body.symbols, body.provider)
        include = set(body.include or [])
        plan = [{"key": s, "label": s.split(":", 1)[-1]} for s in symbols]
        plan.append({"key": "answer", "label": "AI verdict"})
        yield {"type": "plan", "plan": plan}

        collected: list[dict[str, Any]] = []
        for symbol in symbols:
            per: dict[str, Any] = {"symbol": symbol}
            if "quote" in include:
                quote = {}
                try:
                    quote = await self.market_service.get_quote(symbol, provider=body.provider)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("deep quote failed for %s: %s", symbol, exc)
                per["quote"] = quote
                yield _stage("done" if quote.get("price") else "error", f"{symbol}|quote", {"quote": quote})
            if "technical" in include:
                tech = await self._technical_snapshot(symbol, body.provider)
                per["technical"] = tech
                yield _stage("done" if tech.get("latest") else "error", f"{symbol}|technical",
                             {"symbol": symbol, **tech})
            if "options" in include:
                options = await self._options_snapshot(symbol)
                per["options"] = options or None
                yield _stage("done" if options else "skipped", f"{symbol}|options",
                             {"options": options or {}})
            if "prediction" in include:
                prediction = await self._prediction_snapshot(symbol, body.provider)
                per["prediction"] = prediction or None
                yield _stage("done" if prediction else "error", f"{symbol}|prediction",
                             {"prediction": prediction or {}})
            collected.append(per)

        answer, confidence = await self._verdict(body.question, symbols, collected, body.provider)
        yield {
            "type": "answer",
            "data": {
                "answer": answer,
                "confidence": confidence,
                "symbol": ", ".join(symbols),
                "sources": self._sources(collected),
            },
        }

    async def run(self, body: Any) -> dict:
        """Non-streaming convenience: collect all events into one payload."""
        events: list[dict[str, Any]] = []
        async for ev in self.stream(body):
            events.append(ev)
        plan = next((e["plan"] for e in events if e["type"] == "plan"), [])
        stages = [e for e in events if e["type"] == "stage"]
        answer = next((e["data"] for e in events if e["type"] == "answer"), None)
        return {"plan": plan, "stages": stages, "answer": answer}

    # --- stages ----------------------------------------------------------------------------

    async def _technical_snapshot(self, symbol: str, provider: str | None) -> dict[str, Any]:
        try:
            history = await self.market_service.get_history_auto(symbol, interval="1d", period="3mo")
        except Exception as exc:  # noqa: BLE001
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
        stoch = ind.stoch_series(highs, lows, closes)
        supertrend = ind.supertrend_series(highs, lows, closes)
        dmi = ind.dmi_series(highs, lows, closes)
        return {
            "symbol": symbol,
            "last_close": round(closes[-1], 4),
            "rsi": ind.rsi_series(closes, 14)[-1],
            "macd": macd["macd"][-1],
            "macd_signal": macd["signal"][-1],
            "atr": ind.atr(highs, lows, closes, 14),
            "vwap": ind.vwap(highs, lows, closes, vols),
            "stoch_k": stoch["%K"][-1],
            "stoch_d": stoch["%D"][-1],
            "supertrend": supertrend["trend"][-1],
            "adx": dmi["adx"][-1],
            "plus_di": dmi["plus_di"][-1],
            "minus_di": dmi["minus_di"][-1],
            "cci": ind.cci_series(highs, lows, closes, 20)[-1],
            "mfi": ind.mfi_series(highs, lows, closes, vols, 14)[-1],
            "latest": latest,
        }

    async def _options_snapshot(self, symbol: str) -> dict[str, Any]:
        ex = symbol.split(":", 1)[0] if ":" in symbol else ""
        if ex not in {"NSE", "BSE", "NSEFO", "BSEFO", "NYSE", "NASDAQ"}:
            return {}
        try:
            sig = await self.signals.signals(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug("deep options skipped for %s: %s", symbol, exc)
            return {}
        if not sig:
            return {}
        return {k: sig.get(k) for k in (
            "bias", "strategy", "recommendation", "max_pain", "iv_skew",
            "atm_iv", "premium_put_call", "spot_price", "expiry",
        )}

    async def _prediction_snapshot(self, symbol: str, provider: str | None) -> dict[str, Any]:
        try:
            result = await self.prediction.predict(symbol, Timeframe.WEEK)
        except Exception as exc:  # noqa: BLE001
            logger.warning("deep prediction failed for %s: %s", symbol, exc)
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
        }

    # --- resolution + verdict -------------------------------------------------------------

    async def _resolve(self, symbols: list[str], provider: str | None) -> list[str]:
        resolved: list[str] = []
        for raw in [s.strip() for s in symbols if s and s.strip()]:
            if ":" in raw:
                resolved.append(raw.upper())
                continue
            for cand in (f"NSE:{raw.upper()}", f"NYSE:{raw.upper()}", f"NASDAQ:{raw.upper()}"):
                try:
                    quote = await self.market_service.get_quote(cand, provider=provider)
                except Exception:  # noqa: BLE001
                    continue
                if quote and quote.get("price"):
                    resolved.append(cand)
                    break
        return resolved[:5]

    @staticmethod
    def _sources(collected: list[dict[str, Any]]) -> list[str]:
        sources: list[str] = []
        for row in collected:
            if row.get("quote", {}).get("provider"):
                sources.append(f"{row['symbol']}:live-quote:{row['quote']['provider']}")
            if row.get("technical", {}).get("latest"):
                sources.append(f"{row['symbol']}:technical:indicators")
            if row.get("options"):
                sources.append(f"{row['symbol']}:options:chain")
            if row.get("prediction"):
                sources.append(f"{row['symbol']}:prediction:engine")
        return sources

    async def _verdict(
        self,
        question: str,
        symbols: list[str],
        collected: list[dict[str, Any]],
        provider: str | None,
    ) -> tuple[str, float]:
        compact = []
        for row in collected:
            per = {"symbol": row["symbol"]}
            q = row.get("quote") or {}
            per["quote"] = {k: q.get(k) for k in ("name", "price", "day_change_pct", "currency", "sector")}
            t = row.get("technical") or {}
            per["technical"] = {k: t.get(k) for k in (
                "last_close", "rsi", "macd", "macd_signal", "atr", "vwap",
                "stoch_k", "stoch_d", "supertrend", "adx", "plus_di", "minus_di", "cci", "mfi",
            )}
            per["technical"]["latest"] = t.get("latest")
            per["options"] = row.get("options")
            p = row.get("prediction") or {}
            per["prediction"] = {k: p.get(k) for k in (
                "current_price", "predicted_price", "expected_return", "confidence",
                "action", "bull_case", "base_case", "bear_case", "factors",
            )}
            compact.append(per)
        prompt = (
            f"User question: {question}\n\n"
            f"Symbols requested: {', '.join(symbols)}\n\n"
            f"Real StockOS data per symbol:\n{json.dumps(compact, default=str)[:22000]}"
        )
        confidence = self._avg_confidence(collected)
        try:
            text = await gateway.chat(
                [
                    {"role": "system", "content": ASYSTEM},
                    {"role": "user", "content": prompt},
                ],
                provider=provider,
                temperature=0.4,
            )
            if text and text.strip():
                return text.strip(), confidence
        except Exception as exc:  # noqa: BLE001
            logger.warning("deep LLM verdict failed: %s", exc)
        return self._deterministic_verdict(question, symbols, collected), confidence

    @staticmethod
    def _avg_confidence(collected: list[dict[str, Any]]) -> float:
        confs = [
            float(r["prediction"].get("confidence") or 0.5)
            for r in collected
            if r.get("prediction") and r["prediction"].get("confidence")
        ]
        if not confs:
            return 0.5
        return round(sum(confs) / len(confs), 3)

    @staticmethod
    def _deterministic_verdict(
        question: str, symbols: list[str], collected: list[dict[str, Any]]
    ) -> str:
        lines = [f"**Deep analysis — {', '.join(symbols)}**\n", f"Question: *{question}*", ""]
        for row in collected:
            sym = row["symbol"]
            q = row.get("quote") or {}
            t = row.get("technical") or {}
            o = row.get("options") or {}
            p = row.get("prediction") or {}
            lines.append(f"### {sym}")
            if q.get("price"):
                chg = q.get("day_change_pct")
                lines.append(f"- Last {q['price']} ({f'{chg:+.2f}%' if chg is not None else 'n/a'}).")
            if t.get("rsi") is not None:
                zone = "overbought" if t["rsi"] > 70 else "oversold" if t["rsi"] < 30 else "neutral"
                lines.append(f"- RSI(14) {t['rsi']:.1f} ({zone}); Supertrend {t.get('supertrend') or 'n/a'}; "
                             f"ADX {t.get('adx') or 'n/a'}.")
            if p.get("action"):
                lines.append(
                    f"- Deterministic engine: **{p['action']}** "
                    f"(conf {p.get('confidence', 0):.0%}, ER {p.get('expected_return', 0):+.1%})."
                )
            if o.get("bias"):
                lines.append(f"- Options bias: **{o['bias']}** (ATM IV {o.get('atm_iv') or '—'}).")
            lines.append("")
        lines.append("\n*Live data summary — LLM verdict unavailable.*")
        lines.append("\n*Research only, not investment advice.*")
        return "\n".join(lines)


deep_analysis_engine = DeepAnalysisEngine()