"""Options analysis engine with Greeks calculation and strategy builder."""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import numpy as np
from scipy import stats
from enum import Enum

from app.services.data.providers.base import OptionsUnavailableError

@dataclass
class OptionGreeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    
@dataclass
class OptionChain:
    symbol: str
    expiry: datetime
    spot_price: float
    calls: List[Dict]
    puts: List[Dict]
    max_pain: Optional[float] = None
    pcr: Optional[float] = None  # Put-Call Ratio
    iv_rank: float = 0.0
    expiries: List[str] = field(default_factory=list)
    
@dataclass 
class OptionStrategy:
    name: str
    legs: List[Dict]
    max_profit: float
    max_loss: float
    breakeven: List[float]
    probability_profit: float
    expected_return: float
    greeks: OptionGreeks
    
class StrategyType(Enum):
    COVERED_CALL = "covered_call"
    CASH_SECURED_PUT = "cash_secured_put"
    IRON_CONDOR = "iron_condor"
    IRON_FLY = "iron_fly"
    STRADDLE = "straddle"
    STRANGLE = "strangle"
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    BUTTERFLY = "butterfly"
    CALENDAR_SPREAD = "calendar_spread"
    DIAGONAL_SPREAD = "diagonal_spread"
    WHEEL = "wheel"
    
class OptionsEngine:
    """Advanced options analysis with Greeks, strategies, and recommendations."""
    
    def __init__(self, market_service=None):
        self.market_service = market_service
        self.risk_free_rate = 0.05  # 5% annual
        
    async def get_option_chain(self, symbol: str, expiry: datetime = None) -> OptionChain:
        """Fetch a real options chain from the data provider.

        No fabricated data: if the provider cannot supply a chain (e.g. NSE is
        blocked for automated access, or the symbol has no listed options) an
        `OptionsUnavailableError` is raised so the caller can report it clearly.
        """
        if self.market_service is None:
            raise OptionsUnavailableError("Options engine has no market data provider configured")

        raw = await self.market_service.get_option_chain(
            symbol, expiry=expiry.isoformat() if expiry else None
        )
        if not raw:
            raise OptionsUnavailableError(f"No options data returned for {symbol}")

        spot_price = raw.get("spot_price")
        calls = list(raw.get("calls") or [])
        puts = list(raw.get("puts") or [])
        if spot_price is None or (not calls and not puts):
            raise OptionsUnavailableError(f"Options feed returned no usable chain for {symbol}")

        if expiry is None:
            raw_expiry = raw.get("expiry")
            if raw_expiry:
                try:
                    expiry = datetime.fromisoformat(str(raw_expiry)[:10])
                except ValueError:
                    expiry = self._get_next_expiry()
            else:
                expiry = self._get_next_expiry()

        strikes = sorted({float(r["strike"]) for r in calls} | {float(r["strike"]) for r in puts})
        # Max pain and PCR require open interest; providers without OI (e.g. the
        # TradingView scanner) return None rather than a misleading strike.
        total_oi = sum(float(r.get("oi") or 0) for r in calls) + sum(float(r.get("oi") or 0) for r in puts)
        max_pain = self._calculate_max_pain(calls, puts, strikes) if total_oi > 0 else None
        pcr = self._calculate_pcr(calls, puts) if total_oi > 0 else None
        iv_rank = self._calculate_iv_rank(calls, puts)

        raw_expiries = [str(e) for e in (raw.get("expiries") or [])]
        if not raw_expiries and expiry is not None:
            raw_expiries = [expiry.strftime("%Y-%m-%d")]

        return OptionChain(
            symbol=symbol,
            expiry=expiry,
            spot_price=spot_price,
            calls=calls,
            puts=puts,
            max_pain=max_pain,
            pcr=pcr,
            iv_rank=iv_rank,
            expiries=raw_expiries,
        )
        
    def theoretical_price(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        option_type: str = "call",
        dividend_yield: float = 0
    ) -> float:
        """Black-Scholes theoretical premium for a European option."""
        if volatility <= 0 or time_to_expiry <= 0:
            return max(spot - strike, 0) if option_type.lower() == "call" else max(strike - spot, 0)
        r = self.risk_free_rate
        d1 = (np.log(spot / strike) + (r - dividend_yield + 0.5 * volatility**2) * time_to_expiry) / (
            volatility * np.sqrt(time_to_expiry)
        )
        d2 = d1 - volatility * np.sqrt(time_to_expiry)
        if option_type.lower() == "call":
            return spot * np.exp(-dividend_yield * time_to_expiry) * stats.norm.cdf(d1) - strike * np.exp(
                -r * time_to_expiry
            ) * stats.norm.cdf(d2)
        return strike * np.exp(-r * time_to_expiry) * stats.norm.cdf(-d2) - spot * np.exp(
            -dividend_yield * time_to_expiry
        ) * stats.norm.cdf(-d1)

    def calculate_greeks(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        option_type: str = "call",
        dividend_yield: float = 0
    ) -> OptionGreeks:
        """Calculate option Greeks using Black-Scholes model."""
        
        r = self.risk_free_rate
        t = time_to_expiry
        
        # Calculate d1 and d2
        d1 = (np.log(spot/strike) + (r - dividend_yield + 0.5*volatility**2)*t) / (volatility*np.sqrt(t))
        d2 = d1 - volatility*np.sqrt(t)
        
        if option_type.lower() == "call":
            delta = np.exp(-dividend_yield*t) * stats.norm.cdf(d1)
            theta = (-spot*stats.norm.pdf(d1)*volatility*np.exp(-dividend_yield*t)/(2*np.sqrt(t))
                    - r*strike*np.exp(-r*t)*stats.norm.cdf(d2)
                    + dividend_yield*spot*np.exp(-dividend_yield*t)*stats.norm.cdf(d1))
        else:  # put
            delta = -np.exp(-dividend_yield*t) * stats.norm.cdf(-d1)
            theta = (-spot*stats.norm.pdf(d1)*volatility*np.exp(-dividend_yield*t)/(2*np.sqrt(t))
                    + r*strike*np.exp(-r*t)*stats.norm.cdf(-d2)
                    - dividend_yield*spot*np.exp(-dividend_yield*t)*stats.norm.cdf(-d1))
            
        # Common Greeks
        gamma = np.exp(-dividend_yield*t) * stats.norm.pdf(d1) / (spot*volatility*np.sqrt(t))
        vega = spot * np.exp(-dividend_yield*t) * stats.norm.pdf(d1) * np.sqrt(t) / 100
        rho = strike * t * np.exp(-r*t) * (stats.norm.cdf(d2) if option_type.lower() == "call" 
                                           else -stats.norm.cdf(-d2)) / 100
        
        # Convert theta to daily
        theta = theta / 365
        
        return OptionGreeks(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            rho=rho
        )
        
    async def analyze_strategy(
        self,
        symbol: str,
        strategy_type: StrategyType,
        strikes: List[float] = None,
        expiry: datetime = None
    ) -> OptionStrategy:
        """Analyze specific option strategy."""
        
        chain = await self.get_option_chain(symbol, expiry)
        spot = chain.spot_price

        if not strikes:
            strikes = self._suggest_strikes(spot, strategy_type)
            
        # Build strategy based on type
        strategy = self._build_strategy(strategy_type, spot, strikes, chain)
        
        # Calculate P&L profile
        strategy.max_profit = self._calculate_max_profit(strategy)
        strategy.max_loss = self._calculate_max_loss(strategy)
        strategy.breakeven = self._calculate_breakeven(strategy)
        
        # Calculate probability of profit
        strategy.probability_profit = self._calculate_pop(strategy, spot)
        
        # Calculate expected return
        strategy.expected_return = self._calculate_expected_return(strategy)
        
        # Aggregate Greeks
        strategy.greeks = self._aggregate_greeks(strategy, spot, chain.expiry)
        
        return strategy
        
    def suggest_strategies(
        self,
        outlook: str,  # bullish, bearish, neutral
        risk_tolerance: str,  # low, medium, high
        chain: OptionChain
    ) -> List[OptionStrategy]:
        """Suggest option strategies based on market outlook and risk tolerance."""
        mapping = {
            ("bullish", "low"): StrategyType.BULL_CALL_SPREAD,
            ("bullish", "medium"): StrategyType.COVERED_CALL,
            ("bullish", "high"): StrategyType.COVERED_CALL,
            ("bearish", "low"): StrategyType.BEAR_PUT_SPREAD,
            ("bearish", "medium"): StrategyType.CASH_SECURED_PUT,
            ("bearish", "high"): StrategyType.CASH_SECURED_PUT,
            ("neutral", "low"): StrategyType.IRON_CONDOR,
            ("neutral", "medium"): StrategyType.BUTTERFLY,
            ("neutral", "high"): StrategyType.STRADDLE,
        }
        spot = chain.spot_price
        strategy_type = mapping.get((outlook, risk_tolerance), StrategyType.IRON_CONDOR)
        strategy = self._build_strategy(strategy_type, spot, [], chain)
        strategy.max_profit = self._calculate_max_profit(strategy)
        strategy.max_loss = self._calculate_max_loss(strategy)
        strategy.breakeven = self._calculate_breakeven(strategy)
        strategy.probability_profit = self._calculate_pop(strategy, spot)
        strategy.expected_return = self._calculate_expected_return(strategy)
        strategy.greeks = self._aggregate_greeks(strategy, spot, chain.expiry)
        return [strategy]
        
    def _calculate_max_pain(self, calls: List, puts: List, strikes: List) -> float:
        """Calculate max pain strike price."""
        min_pain = float('inf')
        max_pain_strike = strikes[0]
        
        for strike in strikes:
            total_pain = 0
            
            # Pain for call holders
            for call in calls:
                if call['strike'] < strike:
                    total_pain += (strike - call['strike']) * call['oi']
                    
            # Pain for put holders  
            for put in puts:
                if put['strike'] > strike:
                    total_pain += (put['strike'] - strike) * put['oi']
                    
            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = strike
                
        return max_pain_strike
        
    def _calculate_pcr(self, calls: List, puts: List) -> float:
        """Calculate Put-Call Ratio."""
        call_oi = sum(c['oi'] for c in calls)
        put_oi = sum(p['oi'] for p in puts)
        return put_oi / call_oi if call_oi > 0 else 1.0
        
    def _calculate_iv_rank(self, calls: List, puts: List) -> float:
        """Calculate IV Rank (0-100)."""
        # Simplified - would use historical IV in production
        current_iv = np.mean([c['iv'] for c in calls] + [p['iv'] for p in puts])
        return min(current_iv * 100, 100)
        
    def _calculate_pop(self, strategy: OptionStrategy, spot: float) -> float:
        """Calculate probability of profit."""
        # Simplified Monte Carlo
        simulations = 1000
        profitable = 0
        
        for _ in range(simulations):
            future_price = spot * np.exp(np.random.normal(0, 0.2))
            pnl = self._calculate_pnl(strategy, future_price)
            if pnl > 0:
                profitable += 1
                
        return profitable / simulations
        
    def _calculate_expected_return(self, strategy: OptionStrategy) -> float:
        """Calculate expected return of strategy."""
        if strategy.max_loss == 0:
            return 0
        return (strategy.probability_profit * strategy.max_profit - 
                (1 - strategy.probability_profit) * abs(strategy.max_loss)) / abs(strategy.max_loss)
        
    async def _get_spot_price(self, symbol: str) -> float:
        """Get current spot price (used as a fallback anchor for strategies)."""
        if self.market_service:
            try:
                quote = await self.market_service.get_quote(symbol)
                price = quote.get('price')
                if price:
                    return float(price)
            except Exception:  # noqa: BLE001
                pass
        raise OptionsUnavailableError(f"Could not resolve spot price for {symbol}")

    def _get_next_expiry(self) -> datetime:
        """Get next monthly expiry (third Friday)."""
        today = datetime.now()
        # Find third Friday of next month
        next_month = today.replace(day=1) + timedelta(days=32)
        next_month = next_month.replace(day=1)

        # Find first Friday
        days_ahead = 4 - next_month.weekday()  # Friday is 4
        if days_ahead <= 0:
            days_ahead += 7
        first_friday = next_month + timedelta(days=days_ahead)

        # Third Friday is 14 days later
        return first_friday + timedelta(days=14)

    def _strike_near(self, rows: List[Dict], target: float) -> float:
        """Nearest listed strike to `target`, falling back to the rounded target."""
        candidates = [float(r.get("strike")) for r in rows if r.get("strike") is not None]
        if not candidates:
            return round(float(target), 2)
        return min(candidates, key=lambda x: abs(x - float(target)))

    def _suggest_strikes(self, spot: float, strategy_type: StrategyType) -> List[float]:
        """Anchor strikes around spot for a strategy type."""
        if strategy_type == StrategyType.IRON_CONDOR:
            return [spot * 0.90, spot * 0.95, spot * 1.05, spot * 1.10]
        if strategy_type == StrategyType.IRON_FLY:
            return [spot * 0.95, spot, spot * 1.05]
        if strategy_type == StrategyType.STRADDLE:
            return [spot, spot]
        if strategy_type == StrategyType.STRANGLE:
            return [spot * 0.95, spot * 1.05]
        if strategy_type == StrategyType.BULL_CALL_SPREAD:
            return [spot, spot * 1.05]
        if strategy_type == StrategyType.BEAR_PUT_SPREAD:
            return [spot, spot * 0.95]
        if strategy_type == StrategyType.BUTTERFLY:
            return [spot * 0.95, spot, spot * 1.05]
        if strategy_type == StrategyType.COVERED_CALL:
            return [spot, spot * 1.05]
        if strategy_type == StrategyType.CASH_SECURED_PUT:
            return [spot * 0.95]
        if strategy_type in (StrategyType.CALENDAR_SPREAD, StrategyType.DIAGONAL_SPREAD, StrategyType.WHEEL):
            return [spot * 0.95, spot * 1.05]
        return [spot * 0.95, spot, spot * 1.05]

    def _option_price(self, chain: OptionChain, strike: float, kind: str) -> float:
        """Mid price for a listed strike; 0 if not listed."""
        rows = chain.calls if kind == "call" else chain.puts
        for r in rows:
            if float(r.get("strike", 0)) == float(strike):
                bid = r.get("bid") or 0
                ask = r.get("ask") or 0
                if bid or ask:
                    return (float(bid) + float(ask)) / 2
                return float(r.get("last") or 0)
        return 0.0

    def _build_strategy(
        self,
        strategy_type: StrategyType,
        spot: float,
        strikes: List[float],
        chain: OptionChain,
    ) -> OptionStrategy:
        """Build a concrete strategy with real chain prices (mid quotes)."""
        def near(kind: str, target: float) -> float:
            return self._strike_near(chain.calls if kind == "call" else chain.puts, target)

        def call_price(k: float) -> float:
            return self._option_price(chain, k, "call")

        def put_price(k: float) -> float:
            return self._option_price(chain, k, "put")

        legs: List[Dict] = []

        if strategy_type == StrategyType.IRON_CONDOR:
            k_long_put, k_short_put, k_short_call, k_long_call = (
                near("put", spot * 0.90), near("put", spot * 0.95),
                near("call", spot * 1.05), near("call", spot * 1.10),
            )
            legs = [
                {'type': 'buy_put', 'strike': k_long_put, 'qty': 1, 'price': put_price(k_long_put)},
                {'type': 'sell_put', 'strike': k_short_put, 'qty': 1, 'price': put_price(k_short_put)},
                {'type': 'sell_call', 'strike': k_short_call, 'qty': 1, 'price': call_price(k_short_call)},
                {'type': 'buy_call', 'strike': k_long_call, 'qty': 1, 'price': call_price(k_long_call)},
            ]
        elif strategy_type == StrategyType.STRADDLE:
            k = near("call", spot)
            legs = [
                {'type': 'buy_call', 'strike': k, 'qty': 1, 'price': call_price(k)},
                {'type': 'buy_put', 'strike': k, 'qty': 1, 'price': put_price(k)},
            ]
        elif strategy_type == StrategyType.STRANGLE:
            kp, kc = near("put", spot * 0.95), near("call", spot * 1.05)
            legs = [
                {'type': 'buy_put', 'strike': kp, 'qty': 1, 'price': put_price(kp)},
                {'type': 'buy_call', 'strike': kc, 'qty': 1, 'price': call_price(kc)},
            ]
        elif strategy_type == StrategyType.BULL_CALL_SPREAD:
            k1, k2 = near("call", spot), near("call", spot * 1.05)
            legs = [
                {'type': 'buy_call', 'strike': k1, 'qty': 1, 'price': call_price(k1)},
                {'type': 'sell_call', 'strike': k2, 'qty': 1, 'price': call_price(k2)},
            ]
        elif strategy_type == StrategyType.BEAR_PUT_SPREAD:
            k1, k2 = near("put", spot), near("put", spot * 0.95)
            legs = [
                {'type': 'buy_put', 'strike': k1, 'qty': 1, 'price': put_price(k1)},
                {'type': 'sell_put', 'strike': k2, 'qty': 1, 'price': put_price(k2)},
            ]
        elif strategy_type == StrategyType.BUTTERFLY:
            k1, k2, k3 = near("call", spot * 0.95), near("call", spot), near("call", spot * 1.05)
            legs = [
                {'type': 'buy_call', 'strike': k1, 'qty': 1, 'price': call_price(k1)},
                {'type': 'sell_call', 'strike': k2, 'qty': 2, 'price': call_price(k2)},
                {'type': 'buy_call', 'strike': k3, 'qty': 1, 'price': call_price(k3)},
            ]
        elif strategy_type == StrategyType.COVERED_CALL:
            kc = near("call", spot * 1.05)
            legs = [
                {'type': 'buy_stock', 'strike': spot, 'qty': 1, 'price': spot},
                {'type': 'sell_call', 'strike': kc, 'qty': 1, 'price': call_price(kc)},
            ]
        elif strategy_type == StrategyType.CASH_SECURED_PUT:
            kp = near("put", spot * 0.95)
            legs = [
                {'type': 'sell_put', 'strike': kp, 'qty': 1, 'price': put_price(kp)},
            ]
        else:  # calendar / diagonal / wheel -> short put + long call proxy
            kp, kc = near("put", spot * 0.95), near("call", spot * 1.05)
            legs = [
                {'type': 'sell_put', 'strike': kp, 'qty': 1, 'price': put_price(kp)},
                {'type': 'buy_call', 'strike': kc, 'qty': 1, 'price': call_price(kc)},
            ]

        return OptionStrategy(
            name=strategy_type.value.replace("_", " ").title(),
            legs=legs,
            max_profit=0.0,
            max_loss=0.0,
            breakeven=[],
            probability_profit=0.0,
            expected_return=0.0,
            greeks=OptionGreeks(0.0, 0.0, 0.0, 0.0, 0.0),
        )

    def _leg_pnl(self, leg: Dict, spot: float) -> float:
        """P&L of a single leg at expiry for a given spot price."""
        typ = leg["type"]
        strike = float(leg["strike"])
        qty = int(leg.get("qty", 1))
        price = float(leg.get("price") or 0)
        if typ == "buy_stock":
            return qty * (spot - strike)
        if typ == "buy_call":
            return qty * (max(spot - strike, 0) - price)
        if typ == "sell_call":
            return qty * (price - max(spot - strike, 0))
        if typ == "buy_put":
            return qty * (max(strike - spot, 0) - price)
        if typ == "sell_put":
            return qty * (price - max(strike - spot, 0))
        return 0.0

    def _calculate_pnl(self, strategy: OptionStrategy, spot: float) -> float:
        """Total strategy P&L at expiry for a given spot."""
        return sum(self._leg_pnl(leg, spot) for leg in strategy.legs)

    def _profit_points(self, strategy: OptionStrategy) -> List[float]:
        """Breakpoints of the piecewise-linear P&L profile."""
        strikes = sorted({float(l["strike"]) for l in strategy.legs})
        if not strikes:
            return [0.0, 1.0]
        return [0.0, *strikes, strikes[-1] * 10]

    def _calculate_max_profit(self, strategy: OptionStrategy) -> float:
        """Max P&L over the strategy's piecewise-linear profile."""
        return max(self._calculate_pnl(strategy, s) for s in self._profit_points(strategy))

    def _calculate_max_loss(self, strategy: OptionStrategy) -> float:
        """Max loss (min P&L) over the strategy's profile."""
        return min(self._calculate_pnl(strategy, s) for s in self._profit_points(strategy))

    def _calculate_breakeven(self, strategy: OptionStrategy) -> List[float]:
        """Spot prices where strategy P&L crosses zero."""
        points = self._profit_points(strategy)
        breakevens: List[float] = []
        for a, b in zip(points, points[1:]):
            pa = self._calculate_pnl(strategy, a)
            pb = self._calculate_pnl(strategy, b)
            if pa == 0:
                breakevens.append(a)
            elif (pa < 0) != (pb < 0):
                t = pa / (pa - pb)
                breakevens.append(a + t * (b - a))
        return sorted(round(float(x), 2) for x in dict.fromkeys(breakevens))

    def _aggregate_greeks(
        self, strategy: OptionStrategy, spot: float, expiry: datetime
    ) -> OptionGreeks:
        """Sum Black-Scholes Greeks across legs (shorts negated)."""
        days = max((expiry - datetime.now()).days, 1) if expiry else 30
        tte = days / 365
        total = OptionGreeks(0.0, 0.0, 0.0, 0.0, 0.0)
        for leg in strategy.legs:
            typ = leg["type"]
            if "stock" in typ:
                continue
            option_type = "call" if "call" in typ else "put"
            sign = 1.0 if typ.startswith("buy") else -1.0
            g = self.calculate_greeks(spot, float(leg["strike"]), tte, 0.3, option_type)
            total.delta += sign * g.delta
            total.gamma += sign * g.gamma
            total.theta += sign * g.theta
            total.vega += sign * g.vega
            total.rho += sign * g.rho
        return total