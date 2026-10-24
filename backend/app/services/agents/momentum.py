"""Momentum and swing trading agent — real price data only.

Momentum indicators are computed exclusively from real StockOS candles. No
random or hand-written sample prices are ever used: when a symbol has <30
candles the agent reports insufficient data honestly. The no-symbol scan path
does not invent stocks either — it points the user at the real scanners.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from .base import Agent, AgentResult as AgentResponse, AgentContext


class MomentumAgent(Agent):
    """Agent specialized in momentum and swing trading analysis."""

    name = "momentum_trader"
    description = "Identifies momentum and swing trading opportunities"

    async def run(self, ctx: AgentContext) -> AgentResponse:
        """Analyze momentum and swing opportunities."""
        symbol = ctx.symbol
        if not symbol:
            return self._no_symbol_response(ctx.task)

        data = await self._get_price_data(symbol)
        prices = data.get("prices", [])
        if len(prices) < 30:
            return AgentResponse(
                agent=self.name,
                content=(
                    f"## Momentum Analysis: {symbol}\n\n"
                    "Insufficient real candle history (< 30 sessions) to compute "
                    "momentum indicators. No numbers are fabricated; please retry once "
                    "more history is available (or use a symbol with a longer feed)."
                ),
                data={"momentum": {"status": "insufficient_data"}},
                confidence=0.2,
                sources=["price_action"],
            )

        momentum = self._calculate_momentum(data)
        patterns = self._identify_patterns(data)
        signals = self._generate_signals(momentum, patterns)
        content = self._format_analysis(symbol, momentum, patterns, signals)

        return AgentResponse(
            agent=self.name,
            content=content,
            data={"momentum": momentum, "patterns": patterns, "signals": signals},
            confidence=signals.get("confidence", 0.7),
            sources=["price_action", "momentum_indicators", "pattern_recognition"],
        )

    def _calculate_momentum(self, data: dict) -> dict:
        """Momentum indicators over real candles (min 30 bars)."""
        prices: list[float] = data.get("prices", []) or []
        n = len(prices)
        if n < 30:
            return {"status": "insufficient_data"}

        roc: dict[str, float] = {}
        for p in (5, 10, 20):
            if n > p:
                roc[f"roc_{p}"] = round((prices[-1] - prices[-p - 1]) / prices[-p - 1] * 100, 2)
            else:
                roc[f"roc_{p}"] = 0.0

        sma_10 = float(np.mean(prices[-10:]))
        sma_20 = float(np.mean(prices[-20:]))
        sma_50 = float(np.mean(prices[-50:])) if n >= 50 else sma_20

        gains, losses = [], []
        for i in range(1, min(14, n)):
            change = prices[-i] - prices[-i - 1]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))
        avg_gain = float(np.mean(gains)) if gains else 0.0
        avg_loss = float(np.mean(losses)) if losses else 1.0
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        rsi = round(100.0 - (100.0 / (1.0 + rs)), 2)

        if prices[-1] > sma_20 > sma_50:
            trend = "up"
        elif prices[-1] < sma_20 < sma_50:
            trend = "down"
        else:
            trend = "sideways"

        return {
            **roc,
            "price_vs_sma10": round((prices[-1] - sma_10) / sma_10 * 100, 2),
            "price_vs_sma20": round((prices[-1] - sma_20) / sma_20 * 100, 2),
            "price_vs_sma50": round((prices[-1] - sma_50) / sma_50 * 100, 2),
            "rsi": rsi,
            "trend": trend,
        }

    def _identify_patterns(self, data: dict) -> list[dict]:
        """Chart patterns from real candles (never fabricated)."""
        prices: list[float] = data.get("prices", []) or []
        if len(prices) < 30:
            return []

        patterns: list[dict] = []
        if self._is_flag_pattern(prices):
            patterns.append({"name": "Flag", "type": "continuation", "strength": 0.7})
        if self._is_cup_handle(prices):
            patterns.append({"name": "Cup and Handle", "type": "bullish", "strength": 0.8})
        double = self._find_double_patterns(prices)
        if double:
            patterns.append(double)
        if self._is_breakout(prices, data.get("volumes", [])):
            patterns.append({"name": "Breakout", "type": "bullish", "strength": 0.75})
        return patterns

    def _generate_signals(self, momentum: dict, patterns: list[dict]) -> dict:
        """Trading signals from the real momentum + real pattern output."""
        signal = "neutral"
        strength = 0.5
        entry_points: list[str] = []
        exit_points: list[str] = []

        rsi = momentum.get("rsi", 50)
        if rsi < 30:
            signal = "buy"
            strength += 0.2
            entry_points.append("RSI oversold")
        elif rsi > 70:
            signal = "sell"
            strength += 0.2
            exit_points.append("RSI overbought")

        if momentum.get("trend") == "up" and momentum.get("roc_10", 0) > 5:
            signal = "buy"
            strength += 0.15
            entry_points.append("Strong upward momentum")
        elif momentum.get("trend") == "down" and momentum.get("roc_10", 0) < -5:
            signal = "sell"
            strength += 0.15
            exit_points.append("Strong downward momentum")

        for pattern in patterns:
            if pattern["type"] == "bullish":
                signal = "buy"
                strength += pattern["strength"] * 0.2
                entry_points.append(f"{pattern['name']} pattern")
            elif pattern["type"] == "bearish":
                signal = "sell"
                strength += pattern["strength"] * 0.2
                exit_points.append(f"{pattern['name']} pattern")

        return {
            "signal": signal,
            "strength": round(min(strength, 1.0), 3),
            "confidence": round(min(strength * 0.8, 0.95), 3),
            "entry_points": entry_points,
            "exit_points": exit_points,
            "risk_reward": self._calculate_risk_reward(momentum),
        }

    def _is_flag_pattern(self, prices: list[float]) -> bool:
        if len(prices) < 30:
            return False
        recent = prices[-10:]
        prior = prices[-20:-10]
        prior_move = (max(prior) - min(prior)) / min(prior) if min(prior) else 0
        recent_range = (max(recent) - min(recent)) / min(recent) if min(recent) else 0
        return prior_move > 0.1 and recent_range < 0.05

    def _is_cup_handle(self, prices: list[float]) -> bool:
        if len(prices) < 30:
            return False
        left_peak = max(prices[-30:-20])
        bottom = min(prices[-20:-10])
        right_peak = max(prices[-10:])
        is_cup = abs(left_peak - right_peak) / left_peak < 0.05 if left_peak else False
        has_depth = (left_peak - bottom) / left_peak > 0.1 if left_peak else False
        return is_cup and has_depth

    def _find_double_patterns(self, prices: list[float]) -> Optional[dict]:
        if len(prices) < 30:
            return None
        highs, lows = [], []
        for i in range(1, len(prices) - 1):
            if prices[i] > prices[i - 1] and prices[i] > prices[i + 1]:
                highs.append((i, prices[i]))
            elif prices[i] < prices[i - 1] and prices[i] < prices[i + 1]:
                lows.append((i, prices[i]))
        if len(highs) >= 2 and abs(highs[-1][1] - highs[-2][1]) / highs[-1][1] < 0.03:
            return {"name": "Double Top", "type": "bearish", "strength": 0.7}
        if len(lows) >= 2 and abs(lows[-1][1] - lows[-2][1]) / lows[-1][1] < 0.03:
            return {"name": "Double Bottom", "type": "bullish", "strength": 0.7}
        return None

    def _is_breakout(self, prices: list[float], volumes: list[float]) -> bool:
        if len(prices) < 30:
            return False
        recent_high = max(prices[-5:])
        prev_high = max(prices[-20:-5])
        vol_surge = False
        if volumes and len(volumes) >= 20:
            recent_vol = float(np.mean(volumes[-5:]))
            avg_vol = float(np.mean(volumes[-20:]))
            vol_surge = recent_vol > avg_vol * 1.5
        return recent_high > prev_high * 1.02 and (vol_surge or not volumes)

    def _calculate_risk_reward(self, momentum: dict) -> float:
        if momentum.get("trend") == "up":
            return 2.5
        if momentum.get("trend") == "down":
            return 0.8
        return 1.5

    def _format_analysis(
        self, symbol: str, momentum: dict, patterns: list[dict], signals: dict
    ) -> str:
        report = [f"## Momentum Analysis: {symbol}", ""]
        report.append("### Momentum Indicators (real candles)")
        report.append(f"- 5-day ROC: {momentum.get('roc_5', 0):.2f}%")
        report.append(f"- 10-day ROC: {momentum.get('roc_10', 0):.2f}%")
        report.append(f"- RSI: {momentum.get('rsi', 50):.1f}")
        report.append(f"- Trend: **{momentum.get('trend', 'neutral').upper()}**")
        report.append("")

        if patterns:
            report.append("### Chart Patterns Detected")
            for pattern in patterns:
                report.append(f"- **{pattern['name']}** ({pattern['type']}) - Strength: {pattern['strength']:.1%}")
            report.append("")

        report.append("### Trading Signal")
        icon = "🟢" if signals["signal"] == "buy" else "🔴" if signals["signal"] == "sell" else "🟡"
        report.append(f"{icon} **{signals['signal'].upper()}** (Confidence: {signals['confidence']:.1%})")
        report.append("")
        if signals["entry_points"]:
            report.append("**Entry Points:**")
            report.extend(f"- {p}" for p in signals["entry_points"])
        if signals["exit_points"]:
            report.append("\n**Exit Points:**")
            report.extend(f"- {p}" for p in signals["exit_points"])
        report.append(f"\n**Risk-Reward Ratio:** {signals['risk_reward']:.1f}:1")
        return "\n".join(report)

    async def _get_price_data(self, symbol: str) -> dict:
        """Real OHLCV history from the StockOS market service (never sample)."""
        if not self.market_service:
            return {"prices": [], "volumes": []}
        try:
            data = await self.market_service.get_history(symbol, period="3mo")
        except Exception:  # noqa: BLE001
            return {"prices": [], "volumes": []}
        history = (data or {}).get("candles") or []
        if not history:
            return {"prices": [], "volumes": []}
        prices = [float(h["close"]) for h in history if isinstance(h.get("close"), (int, float))]
        volumes = [float(h.get("volume") or 0) for h in history]
        return {"prices": prices, "volumes": volumes}

    def _no_symbol_response(self, task: str) -> AgentResponse:
        """Honest guidance when no symbol is supplied — no invented picks."""
        content = (
            "## Momentum Scan\n\n"
            "No symbol was provided, so no individual momentum read is computed. "
            "I do not invent watch-list picks.\n\n"
            "Use the **Scanners** page (e.g. `52_week_high`, `rsi_oversold`) which "
            "scan real quotes and candles, or ask for a specific symbol "
            "(e.g. `NSE:RELIANCE`) for a momentum analysis."
        )
        return AgentResponse(
            agent=self.name,
            content=content,
            confidence=0.3,
            sources=["momentum_indicators"],
        )
