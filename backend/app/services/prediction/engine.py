"""AI-powered price prediction engine with multiple timeframes."""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
from dataclasses import dataclass, field
from enum import Enum

from app.core.logging import get_logger

logger = get_logger("prediction.engine")

@dataclass
class PredictionResult:
    symbol: str
    timeframe: str
    current_price: float
    predicted_price: float
    confidence: float
    probability_up: float
    probability_down: float
    expected_return: float
    risk_score: float
    bear_case: float
    base_case: float
    bull_case: float
    reasoning: str
    factors: Dict[str, float]
    action: str = "HOLD"
    horizon: str = "Short-term"
    trading_stats: Dict[str, any] = field(default_factory=dict)
    
class Timeframe(Enum):
    TOMORROW = "1D"
    WEEK = "1W"
    MONTH = "1M"
    QUARTER = "3M"
    HALF_YEAR = "6M"
    YEAR = "1Y"
    THREE_YEARS = "3Y"
    FIVE_YEARS = "5Y"
    
class PredictionEngine:
    """Multi-factor AI prediction engine combining technical, fundamental, and sentiment."""
    
    def __init__(self, market_service=None, llm_gateway=None):
        self.market_service = market_service
        self.llm_gateway = llm_gateway
        
    async def predict(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.WEEK,
        *,
        use_agent: bool = False,
        option: Optional[dict] = None,
    ) -> PredictionResult:
        """Generate price prediction for given timeframe.

        ``option`` (optional) is ``{"type": "CE"|"PE", "strike": float, "expiry": str|None}`` —
        a specific Indian option contract (e.g. NSE:BANKNIFTY 44200 CE). When given,
        the engine:
        - analyses the **underlying index** exactly as usual (real candles, stats),
        - loads the real option chain, picks the leg at that strike/expiry,
        - drives the **option premium** off the index move × the leg's delta, and
        - returns both the option leg view (``trading_stats.option_leg``) and the
          underlying index view (``trading_stats.underlying``) so the user sees the
          index AND the contract together.

        ``use_agent=True`` appends the LLM-backed Stock Analysis agent reasoning on
        top of the deterministic quantitative note — both paths run, so the report
        shows the algorithm AND the agent's view together. Falls back to the
        deterministic note alone when the LLM is unreachable.
        """

        # Fetch historical data (full candles so trading stats are real, too)
        candles = await self._get_candles(symbol)
        if not candles:
            raise ValueError(f"No price history available for {symbol} (data provider returned no candles)")
        closes = [float(c["close"]) for c in candles if isinstance(c.get("close"), (int, float))]
        if len(closes) < 20:
            raise ValueError(
                f"Insufficient price history for {symbol} ({len(closes)} candles; need at least 20). "
                "This can happen during Yahoo rate-limiting — retry in a minute."
            )
        current_price = closes[-1]

        # Calculate technical factors
        tech_score = self._calculate_technical_score(closes)

        # Calculate fundamental factors from real fundamentals (when available)
        fundamental_score = await self._calculate_fundamental_score(symbol)

        # Sentiment is a deterministic proxy derived from the symbol's real
        # short-term price action (never random, never hardcoded neutral).
        sentiment_score = self._calculate_sentiment_score(closes)
        
        # Combine factors with weights
        weights = {
            "technical": 0.4,
            "fundamental": 0.35,
            "sentiment": 0.25
        }
        
        combined_score = (
            weights["technical"] * tech_score +
            weights["fundamental"] * fundamental_score +
            weights["sentiment"] * sentiment_score
        )
        
        # Generate predictions based on timeframe
        predictions = self._generate_predictions(
            current_price, 
            combined_score, 
            timeframe
        )
        
        # Calculate confidence based on data quality and consensus
        confidence = self._calculate_confidence(tech_score, fundamental_score, sentiment_score)

        trading_stats = await self._build_trading_stats(symbol, candles)
        action = self._action_from_score(combined_score, timeframe)
        horizon = self._horizon_from_timeframe(timeframe)

        # Option-leg analysis: predict the tracked CE/PE contract premium AND
        # the underlying index, presenting them side by side.
        current_price_display = current_price
        predicted_display = predictions["base"]
        bear_display = predictions["bear"]
        base_display = predictions["base"]
        bull_display = predictions["bull"]
        expected_ret = predictions["expected_return"]

        option_leg = None
        if option and option.get("strike") is not None:
            option_leg = await self._build_option_leg(symbol, trading_stats, option, expected_ret)
            if option_leg:
                current_price_display = option_leg.get("current_premium") or current_price
                predicted_display = option_leg.get("predicted_premium") or predicted_display
                bear_display = option_leg.get("bear_case") or bear_display
                base_display = option_leg.get("base_case") or base_display
                bull_display = option_leg.get("bull_case") or bull_display
                expected_ret = option_leg.get("expected_return") or expected_ret
                trading_stats["option_leg"] = option_leg
                trading_stats["underlying"] = {
                    "symbol": symbol,
                    "current_price": current_price,
                    "predicted_price": predictions["base"],
                }

        prediction_data = {
            "timeframe": timeframe.value,
            "current_price": current_price_display,
            "predicted_price": predicted_display,
            "base_case": base_display,
            "bull_case": bull_display,
            "bear_case": bear_display,
            "expected_return": expected_ret,
            "probability_up": predictions["prob_up"],
            "probability_down": predictions["prob_down"],
            "risk_score": predictions["risk"],
            "confidence": confidence,
            "action": action,
            "horizon": horizon,
        }

        # Generate reasoning (LLM Stock Analysis agent when requested, else the
        # deterministic note; both are built only from the real data above).
        reasoning = self._generate_reasoning(
            symbol, timeframe, tech_score, fundamental_score, sentiment_score, trading_stats, action
        )
        # BOTH outputs run: the deterministic quantitative note (above) always
        # stays; when the LLM agent succeeds we append its view under a clear
        # heading instead of discarding the algorithm's own analysis.
        if use_agent:
            agent_reasoning = await self._agent_reasoning(
                symbol, candles, trading_stats, prediction_data
            )
            if agent_reasoning:
                reasoning = (
                    reasoning
                    + "\n\n---\n\n### AI Pro view (Stock Analysis agent)\n\n"
                    + agent_reasoning
                )

        return PredictionResult(
            symbol=symbol,
            timeframe=timeframe.value,
            current_price=current_price_display,
            predicted_price=predicted_display,
            confidence=confidence,
            probability_up=predictions["prob_up"],
            probability_down=predictions["prob_down"],
            expected_return=expected_ret,
            risk_score=predictions["risk"],
            bear_case=bear_display,
            base_case=base_display,
            bull_case=bull_display,
            reasoning=reasoning,
            factors={
                "technical": tech_score,
                "fundamental": fundamental_score,
                "sentiment": sentiment_score,
                "momentum": float(self._calculate_momentum(closes)),
                "volatility": float(self._calculate_volatility(closes)),
                "trend": float(self._calculate_trend(closes))
            },
            action=action,
            horizon=horizon,
            trading_stats=trading_stats,
        )
        
    async def _get_candles(self, symbol: str) -> List[Dict[str, any]]:
        """Fetch full candles (close + volume) from the real market data service."""
        if not self.market_service:
            return []
        try:
            data = await self.market_service.get_history(symbol, period="1y")
            return (data or {}).get("candles") or []
        except Exception:  # noqa: BLE001
            return []
    
    async def _get_history(self, symbol: str) -> List[float]:
        """Fetch historical prices from the real market data service."""
        return [float(c["close"]) for c in await self._get_candles(symbol) if isinstance(c.get("close"), (int, float))]

    async def _agent_reasoning(
        self,
        symbol: str,
        candles: List[Dict[str, any]],
        trading_stats: Dict[str, any],
        prediction_data: Dict[str, any],
    ) -> Optional[str]:
        """Run the LLM Stock Analysis agent over the real data for reasoning.

        Returns None on any failure so the caller keeps the deterministic note.
        """
        try:
            from app.services.agents.base import AgentContext
            from app.services.agents.stock_analysis import StockAnalysisAgent

            quote = {}
            fundamentals = {}
            if self.market_service:
                try:
                    quote = await self.market_service.get_quote(symbol)
                except Exception:  # noqa: BLE001
                    quote = {}
                try:
                    fundamentals = await self.market_service.get_fundamentals(symbol)
                except Exception:  # noqa: BLE001
                    fundamentals = {}

            ctx = AgentContext(
                symbol=symbol,
                data={
                    "quote": quote,
                    "fundamentals": fundamentals,
                    "history": {"symbol": symbol, "candles": candles},
                    "trading_stats": trading_stats,
                    "options": trading_stats.get("options"),
                    "prediction": prediction_data,
                },
            )
            result = await StockAnalysisAgent().run(ctx)
            content = (result.content or "").strip()
            return content or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent-based reasoning failed for %s: %s", symbol, exc)
            return None

    async def _options_snapshot(self, symbol: str) -> Optional[Dict[str, any]]:
        """Call/put signals from the live option chain (cached), else None.

        Runs only for NSE/BSE underlyings that carry an Indian option chain and
        uses this engine's market service so failures degrade gracefully.
        """
        ex = symbol.split(":", 1)[0] if ":" in symbol else ""
        if ex not in {"NSE", "BSE", "NSEFO", "BSEFO"} or not self.market_service:
            return None
        try:
            from app.services.options.signals import OptionsSignalsService

            signals = await OptionsSignalsService(market_service=self.market_service).signals(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug("option signals unavailable for %s: %s", symbol, exc)
            return None
        if not signals:
            return None
        return {
            "bias": signals.get("bias"),
            "strategy": signals.get("strategy"),
            "recommendation": signals.get("recommendation"),
            "max_pain": signals.get("max_pain"),
            "iv_skew": signals.get("iv_skew"),
            "atm_iv": signals.get("atm_iv"),
            "avg_iv": signals.get("avg_iv"),
            "premium_put_call": signals.get("premium_put_call"),
            "spot_price": signals.get("spot_price"),
            "expiry": signals.get("expiry"),
        }
            
    async def _build_option_leg(
        self,
        underlying: str,
        trading_stats: Dict[str, any],
        option: Dict[str, any],
        underlying_return: float,
    ) -> Optional[Dict[str, any]]:
        """Analyse a specific CE/PE contract at a strike against the index move.

        Loads the real option chain (cached) for the underlying, picks the
        requested strike & option type, and prices the premium using the leg's
        live IV + delta: premium ≈ intrinsic + (index expected move × delta ×
        spot). Returns the leg view (real Greeks, IV, theo) plus premium
        scenarios, or None when no chain/leg exists (honest degradation).
        """
        opt_type = str(option.get("type") or "CE").upper()
        if opt_type not in {"CE", "PE", "CALL", "PUT"}:
            return None
        if opt_type in {"CE", "CALL"}:
            kind = "call"
        else:
            kind = "put"
        try:
            strike = float(option.get("strike"))
        except (TypeError, ValueError):
            return None
        expiry = option.get("expiry") or None

        ex = underlying.split(":", 1)[0] if ":" in underlying else ""
        if ex not in {"NSE", "BSE", "NSEFO", "BSEFO"} or not self.market_service:
            return None
        try:
            chain = await self.market_service.get_option_chain(underlying, expiry=expiry)
        except Exception as exc:  # noqa: BLE001
            logger.debug("option leg unavailable for %s @ %s: %s", underlying, strike, exc)
            return None
        if not chain:
            return None

        spot = float(chain.get("spot_price") or 0)
        rows = (chain.get(kind + "s") or [])
        used_expiry = chain.get("expiry") or expiry
        available_strikes = sorted(
            {
                float(r.get("strike"))
                for r in (chain.get("calls") or []) + (chain.get("puts") or [])
                if r.get("strike") is not None
            }
        )
        available_expiries = list(chain.get("expiries") or ([used_expiry] if used_expiry else []))
        leg = next((r for r in rows if abs(float(r.get("strike") or 0) - strike) < 0.01), None)
        if leg is None and rows:
            leg = min(rows, key=lambda r: abs(float(r.get("strike") or 0) - strike))
        if leg is None:
            return None

        current_premium = float(leg.get("last") or 0)
        iv = float(leg.get("iv") or 0)
        delta = float(leg.get("delta") or 0)

        # Premium move is driven by the underlying's projected move through the
        # leg's delta (signed). A put (negative delta) rises when the index
        # falls, a call (positive delta) rises when the index rises — handled
        # automatically by the signed delta.
        adjust = delta * (underlying_return or 0)
        premium_base = max(0.01, current_premium * (1 + adjust))
        premium_bull = max(premium_base, current_premium * (1 + adjust + abs(delta) * 0.1))
        premium_bear = max(0.01, current_premium * (1 + min(adjust - abs(delta) * 0.1, 0.0)))

        if spot and current_premium:
            moneyness = (spot - strike) / strike
        else:
            moneyness = None

        return {
            "underlying": underlying,
            "option_type": kind.upper(),
            "requested_strike": strike,
            "strike": float(leg.get("strike") or strike),
            "expiry": used_expiry,
            "current_premium": round(current_premium, 2),
            "predicted_premium": round(premium_base, 2),
            "base_case": round(premium_base, 2),
            "bull_case": round(premium_bull, 2),
            "bear_case": round(premium_bear, 2),
            "expected_return": (premium_base / current_premium - 1) if current_premium else 0.0,
            "iv": round(iv, 4),
            "delta": round(delta, 4),
            "gamma": round(float(leg.get("gamma") or 0), 4),
            "theta": round(float(leg.get("theta") or 0), 4),
            "vega": round(float(leg.get("vega") or 0), 4),
            "spot_price": round(spot, 2),
            "moneyness": round(moneyness, 4) if moneyness is not None else None,
            "available_strikes": available_strikes,
            "available_expiries": available_expiries,
        }

    async def _calculate_fundamental_score(self, symbol: str) -> float:
        """Fundamental score (0-1) from real metrics when available, else neutral 0.5."""
        if not self.market_service:
            return 0.5
        try:
            data = await self.market_service.get_fundamentals(symbol)
        except Exception:  # noqa: BLE001
            return 0.5
        base = (data or {}).get("base") or {}
        if not base:
            base = data or {}
        pe = base.get("trailingPE") or base.get("forwardPE")
        pb = base.get("priceToBook")
        roe = base.get("returnOnEquity")
        margins = base.get("profitMargins")
        if not any(v is not None for v in (pe, pb, roe, margins)):
            return 0.5
        score = 0.5
        if isinstance(pe, (int, float)) and pe:
            score += 0.15 if pe < 25 else -0.15
        if isinstance(pb, (int, float)) and pb:
            score += 0.05 if pb < 3 else -0.05
        if isinstance(roe, (int, float)) and roe:
            score += 0.2 if roe > 0.15 else (0.0 if roe > 0 else -0.2)
        if isinstance(margins, (int, float)) and margins:
            score += 0.1 if margins > 0.1 else 0.0
        return min(max(score, 0), 1)
        
    def _calculate_technical_score(self, closes: List[float]) -> float:
        """Technical factor from the symbol's own RSI, momentum and trend.

        Purely deterministic — driven by the real closes so it varies per
        symbol (up-series scores high, down-series scores low).
        """
        if len(closes) < 20:
            return 0.5
        rsi = self._calculate_rsi(closes)
        momentum = self._calculate_momentum(closes)
        trend = self._calculate_trend(closes)
        # RSI 50 = neutral; map to [-1, 1]
        rsi_signal = max(min((rsi - 50) / 50.0, 1.0), -1.0)
        mom_signal = np.tanh(momentum * 10)
        combined = (0.5 * rsi_signal) + (0.3 * mom_signal) + (0.2 * trend)
        score = 0.5 + 0.45 * float(max(min(combined, 1.0), -1.0))
        return round(min(max(score, 0.05), 0.95), 4)

    def _calculate_sentiment_score(self, history: List[float]) -> float:
        """Deterministic sentiment proxy from the symbol's own price action.

        Uses the 1-week and 1-month moves normalized through tanh so the value
        is stable, real (no randomness), and varies per symbol.
        """
        if len(history) < 5:
            return 0.5
        m1w = (history[-1] / history[-5]) - 1
        m1m = (history[-1] / history[-21]) - 1 if len(history) >= 21 else m1w
        signal = np.tanh((m1w * 4 + m1m * 14))
        return round(min(max(0.5 + 0.45 * float(signal), 0.1), 0.9), 4)
        
    def _generate_predictions(
        self, 
        current_price: float, 
        score: float, 
        timeframe: Timeframe
    ) -> Dict[str, float]:
        """Generate price predictions based on combined score."""
        
        # Timeframe multipliers for expected returns
        multipliers = {
            Timeframe.TOMORROW: 0.02,
            Timeframe.WEEK: 0.05,
            Timeframe.MONTH: 0.08,
            Timeframe.QUARTER: 0.15,
            Timeframe.HALF_YEAR: 0.25,
            Timeframe.YEAR: 0.40,
            Timeframe.THREE_YEARS: 1.0,
            Timeframe.FIVE_YEARS: 1.5
        }
        
        multiplier = multipliers.get(timeframe, 0.1)
        
        # Convert score to expected return
        expected_return = (score - 0.5) * multiplier
        
        # Calculate scenarios
        base_case = current_price * (1 + expected_return)
        volatility = 0.15 * multiplier  # Adjust volatility by timeframe
        
        bear_case = current_price * (1 + expected_return - volatility)
        bull_case = current_price * (1 + expected_return + volatility)
        
        # Calculate probabilities
        prob_up = score
        prob_down = 1 - score
        
        # Risk score based on volatility and timeframe
        risk_score = min(volatility * 2 + (multiplier * 0.3), 1.0)
        
        return {
            "base": base_case,
            "bear": bear_case,
            "bull": bull_case,
            "expected_return": expected_return,
            "prob_up": prob_up,
            "prob_down": prob_down,
            "risk": risk_score
        }
        
    def _calculate_confidence(self, tech: float, fund: float, sent: float) -> float:
        """Calculate prediction confidence based on factor consensus."""
        # Higher confidence when factors agree
        variance = np.var([tech, fund, sent])
        consensus = 1 - (variance * 2)  # Lower variance = higher consensus
        
        # Adjust for extreme values (very bullish/bearish)
        avg_score = np.mean([tech, fund, sent])
        extremity = abs(avg_score - 0.5) * 2  # 0 at 0.5, 1 at 0 or 1
        
        confidence = (consensus * 0.7) + (extremity * 0.3)
        return min(max(confidence, 0.1), 0.95)  # Cap between 10% and 95%
        
    async def _build_trading_stats(self, symbol: str, candles: List[Dict[str, any]]) -> Dict[str, any]:
        """Assemble the real trading statistics shown to the user."""
        closes = [float(c["close"]) for c in candles if isinstance(c.get("close"), (int, float))]
        if not closes:
            return {}
        volumes = [
            float(c.get("volume") or 0)
            for c in candles
            if isinstance(c.get("close"), (int, float))
        ]
        current = closes[-1]

        up = sum(1 for a, b in zip(closes[:-1], closes[1:]) if b > a)
        down = sum(1 for a, b in zip(closes[:-1], closes[1:]) if b < a)
        flat = len(closes) - 1 - up - down

        lo52 = min(closes)
        hi52 = max(closes)
        range_pos = (current - lo52) / (hi52 - lo52) if hi52 > lo52 else 0.5

        avg_vol = float(np.mean(volumes)) if volumes else 0.0
        vol_trend = 0.0
        if len(volumes) >= 10 and avg_vol > 0:
            vol_trend = float(np.mean(volumes[-5:]) / avg_vol)

        atr = self._calculate_atr(candles)
        atr_pct = (atr / current) if current else 0.0

        fundamentals = {}
        sector = industry = market_cap = None
        if self.market_service:
            try:
                fundamentals = await self.market_service.get_fundamentals(symbol)
                base = fundamentals.get("base") or fundamentals or {}
                sector = base.get("sector") if isinstance(base, dict) else None
                industry = base.get("industry") if isinstance(base, dict) else None
                market_cap = base.get("marketCap") if isinstance(base, dict) else None
            except Exception:  # noqa: BLE001
                pass

        stats: Dict[str, any] = {
            "trading_days": len(closes),
            "up_days": up,
            "down_days": down,
            "flat_days": flat,
            "up_ratio": round(up / (up + down), 4) if (up + down) else None,
            "avg_volume": int(avg_vol),
            "volume_trend": round(vol_trend, 3),
            "atr": round(atr, 2),
            "atr_pct": round(atr_pct, 4),
            "range_52w_position": round(range_pos, 4),
            "low_52w": round(lo52, 2),
            "high_52w": round(hi52, 2),
            "volatility": round(float(self._calculate_volatility(closes)), 4),
            "sector": sector,
            "industry": industry,
            "market_cap": market_cap,
            "cap_class": self._cap_class(market_cap, symbol),
            "price_band": self._price_band(current),
            "last_expiry": await self._last_expiry(symbol),
            "options": await self._options_snapshot(symbol),
        }
        return stats

    @staticmethod
    def _cap_class(market_cap: Optional[float], symbol: str) -> str:
        """Classify a market cap into small/mid/large/mega by market currency."""
        if not isinstance(market_cap, (int, float)) or not market_cap:
            return "n/a"
        ex = symbol.split(":")[0] if ":" in symbol else ""
        if ex in {"NSE", "BSE", "BOM", "NSEFO", "BSEFO"}:
            # INR thresholds (₹ Cr): SMALL < 10k Cr, MID < 50k Cr, LARGE < 3L Cr
            if market_cap < 1e11:
                return "SMALL"
            if market_cap < 5e11:
                return "MID"
            if market_cap < 3e12:
                return "LARGE"
            return "MEGA"
        # USD thresholds: SMALL < $2B, MID < $10B, LARGE < $200B
        if market_cap < 2e9:
            return "SMALL"
        if market_cap < 1e10:
            return "MID"
        if market_cap < 2e11:
            return "LARGE"
        return "MEGA"

    @staticmethod
    def _price_band(price: float) -> str:
        if price < 200:
            return "LOW"
        if price < 2000:
            return "MID"
        return "HIGH"

    async def _last_expiry(self, symbol: str) -> Optional[str]:
        """Nearest future option expiry for symbols with a listed chain."""
        ex = symbol.split(":")[0] if ":" in symbol else ""
        if ex not in {"NSE", "BSE", "NSEFO", "BSEFO"}:
            return None
        if not self.market_service:
            return None
        try:
            chain = await self.market_service.get_option_chain(symbol)
            expiries = (chain or {}).get("expiries") or []
            today = datetime.now().date().isoformat()
            future = [e for e in expiries if e >= today]
            return min(future) if future else (expiries[0] if expiries else None)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _action_from_score(score: float, timeframe: Timeframe) -> str:
        """Map the combined score to a plain BUY/SELL/HOLD recommendation."""
        if score > 0.6:
            return "BUY"
        if score < 0.4:
            return "SELL"
        return "HOLD"

    @staticmethod
    def _horizon_from_timeframe(timeframe: Timeframe) -> str:
        if timeframe in {Timeframe.TOMORROW, Timeframe.WEEK}:
            return "Short-term"
        if timeframe in {Timeframe.MONTH, Timeframe.QUARTER}:
            return "Medium-term"
        return "Long-term"

    @staticmethod
    def _calculate_atr(candles: List[Dict[str, any]], period: int = 14) -> float:
        """Average True Range from real candle highs/lows (defaults to daily range)."""
        if not candles:
            return 0.0
        trs = []
        for i in range(1, min(len(candles), period + 1)):
            h = float(candles[i].get("high") or candles[i].get("close") or 0)
            l = float(candles[i].get("low") or candles[i].get("close") or 0)
            pc = float(candles[i - 1].get("close") or 0)
            if not (h and l and pc):
                continue
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        return float(np.mean(trs)) if trs else 0.0

    def _generate_reasoning(
        self, 
        symbol: str, 
        timeframe: Timeframe,
        tech: float, 
        fund: float, 
        sent: float,
        stats: Dict[str, any] = None,
        action: str = "HOLD",
    ) -> str:
        """Generate human-readable prediction reasoning."""

        avg_score = np.mean([tech, fund, sent])
        outlook = "bullish" if avg_score > 0.6 else "bearish" if avg_score < 0.4 else "neutral"

        reasoning = f"Based on comprehensive analysis for {symbol} over {timeframe.value}:\n\n"

        # Technical analysis
        tech_view = "positive" if tech > 0.6 else "negative" if tech < 0.4 else "mixed"
        reasoning += f"• Technical indicators show {tech_view} signals ({tech:.1%} score)\n"
        
        # Fundamental analysis
        fund_view = "strong" if fund > 0.6 else "weak" if fund < 0.4 else "moderate"
        reasoning += f"• Fundamental metrics appear {fund_view} ({fund:.1%} score)\n"
        
        # Sentiment
        sent_view = "optimistic" if sent > 0.6 else "pessimistic" if sent < 0.4 else "neutral"
        reasoning += f"• Short-term price sentiment is {sent_view} ({sent:.1%} score)\n\n"

        # Real trading statistics (when available)
        if stats:
            up_ratio = stats.get("up_ratio")
            if up_ratio is not None:
                reasoning += (
                    f"• Market action: {up_ratio:.0%} of the last "
                    f"{stats.get('trading_days', 0)} sessions closed up "
                    f"({stats.get('up_days')} up / {stats.get('down_days')} down).\n"
                )
            if stats.get("avg_volume"):
                vol_view = "above average" if (stats.get("volume_trend") or 0) > 1.15 else "below average" if (stats.get("volume_trend") or 0) < 0.85 else "normal"
                reasoning += (
                    f"• Volume: avg {int(stats['avg_volume']):,} shares/day, "
                    f"{vol_view} over the last week.\n"
                )
            if stats.get("range_52w_position") is not None:
                reasoning += f"• Price sits at {stats['range_52w_position']:.0%} of its 52-week range.\n"
            if stats.get("last_expiry"):
                reasoning += f"• Nearest options expiry: {stats['last_expiry']}.\n"
            options = stats.get("options")
            if options:
                bias = options.get("bias")
                if bias:
                    reasoning += f"• Options market bias: {bias}."
                if options.get("max_pain") is not None and options.get("spot_price") is not None:
                    reasoning += (
                        f" Max pain {options['max_pain']} vs spot {options['spot_price']}."
                    )
                if options.get("iv_skew") is not None:
                    reasoning += f" IV skew {options['iv_skew']:+}."
                if options.get("atm_iv") is not None:
                    reasoning += (
                        f" ATM IV {options['atm_iv']:.1%}."
                        if options["atm_iv"] > 1
                        else f" ATM IV {options['atm_iv']:.2%}."
                    )
                if options.get("recommendation"):
                    reasoning += f"\n• {options['recommendation']}"
                reasoning += "\n"
            cap_class = stats.get("cap_class")
            if cap_class and cap_class != "n/a":
                reasoning += f"• Cap class: {cap_class}."
            sector = stats.get("sector")
            if sector:
                reasoning += f" Sector: {sector}."
            if cap_class and cap_class != "n/a" or sector:
                reasoning += "\n"
            leg = stats.get("option_leg")
            if leg:
                reasoning += (
                    f"\n### Option leg ({leg.get('option_type')} … strike {leg.get('strike')})\n"
                    f"• Underlying spot {leg.get('spot_price')} · premium {leg.get('current_premium')} "
                    f"· IV {leg.get('iv')} · delta {leg.get('delta')} · theta {leg.get('theta')}.\n"
                    f"• Offered premium path: base {leg.get('base_case')}, bull {leg.get('bull_case')}, "
                    f"bear {leg.get('bear_case')}.\n"
                )
            reasoning += "\n"

        reasoning += f"Overall outlook: {outlook.upper()}\n"
        reasoning += f"Recommended action: {action} ({self._horizon_from_timeframe(timeframe)} view)\n\n"
        reasoning += "Note: This is an AI-generated analysis for research purposes only. "
        reasoning += "Not investment advice. All predictions carry risk."
        
        return reasoning
        
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate Relative Strength Index."""
        if len(prices) < period + 1:
            return 50
            
        deltas = np.diff(prices[-period-1:])
        gains = deltas[deltas > 0].sum() / period
        losses = -deltas[deltas < 0].sum() / period
        
        if losses == 0:
            return 100
        rs = gains / losses
        rsi = 100 - (100 / (1 + rs))
        return rsi
        
    def _calculate_momentum(self, prices: List[float]) -> float:
        """Calculate price momentum."""
        if len(prices) < 20:
            return 0.5
        return (prices[-1] - prices[-20]) / prices[-20]
        
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Calculate price volatility."""
        if len(prices) < 21:
            return 0.2
        returns = np.diff(prices[-21:]) / prices[-21:-1]
        return np.std(returns)
        
    def _calculate_trend(self, prices: List[float]) -> float:
        """Calculate trend strength (-1 to 1)."""
        if len(prices) < 20:
            return 0
        x = np.arange(len(prices[-20:]))
        y = prices[-20:]
        z = np.polyfit(x, y, 1)
        return np.tanh(z[0])  # Normalize to -1 to 1