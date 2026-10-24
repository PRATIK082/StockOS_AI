"""Market scanners and screeners for finding opportunities.

All data comes from the real market-data facade (quotes, OHLCV history,
fundamentals) — never fabricated. Each `ScannerType` runs its own distinct
criteria so results differ per scan; symbols without enough data are skipped.
"""
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum
import asyncio
import math
import numpy as np


@dataclass
class ScanResult:
    symbol: str
    name: str
    price: float
    change_pct: float
    volume: int
    signal_strength: float
    matched_criteria: List[str]


class ScannerType(Enum):
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    MOMENTUM = "momentum"
    VOLUME_SPIKE = "volume_spike"
    NEW_HIGH = "52_week_high"
    NEW_LOW = "52_week_low"
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"
    STRONG_FUNDAMENTALS = "strong_fundamentals"
    VALUE_PICKS = "value_picks"
    GROWTH_STOCKS = "growth_stocks"
    QUALITY_STOCKS = "quality_stocks"
    SWING_TRADE = "swing_candidates"
    INTRADAY = "intraday_candidates"
    OPTIONS_PLAY = "options_candidates"


# Fallback universes (bare tickers resolve via the configured provider); the
# curated universe module is preferred when importable.
_DEFAULT_INDIA = ["NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK", "NSE:INFY", "NSE:ICICIBANK",
                  "NSE:HINDUNILVR", "NSE:ITC", "NSE:SBIN", "NSE:BHARTIARTL", "NSE:KOTAKBANK",
                  "NSE:LT", "NSE:HCLTECH", "NSE:AXISBANK", "NSE:ASIANPAINT", "NSE:MARUTI",
                  "NSE:SUNPHARMA", "NSE:TITAN", "NSE:ULTRACEMCO", "NSE:ONGC", "NSE:NTPC"]
_DEFAULT_US = ["AAPL", "MSFT", "GOOGL", "AMZN", "META",
               "TSLA", "NVDA", "JPM", "V", "JNJ",
               "WMT", "PG", "UNH", "HD", "MA",
               "DIS", "BAC", "PYPL", "NFLX", "ADBE"]


class MarketScanner:
    """Comprehensive market scanner with multiple strategies."""

    def __init__(self, market_service=None, universe=None):
        self.market_service = market_service
        self.universe = universe or {}
        self._cache: Dict[str, Optional[Dict[str, Any]]] = {}

    async def scan(
        self,
        scanner_type: ScannerType,
        market: str = "india",
        limit: int = 20
    ) -> List[ScanResult]:
        """Run scanner and return matching stocks."""
        self._cache = {}
        scanner_func = self._get_scanner_function(scanner_type)
        stocks = self._get_market_universe(market)

        tasks = [scanner_func(symbol) for symbol in stocks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results = [r for r in results if isinstance(r, ScanResult)]
        valid_results.sort(key=lambda x: x.signal_strength, reverse=True)
        return valid_results[:limit]

    async def custom_scan(
        self,
        criteria: Dict[str, Any],
        market: str = "india",
        limit: int = 20
    ) -> List[ScanResult]:
        """Run custom scanner with user-defined criteria."""
        self._cache = {}
        stocks = self._get_market_universe(market)
        results = []
        for symbol in stocks:
            try:
                if await self._matches_criteria(symbol, criteria):
                    result = await self._create_scan_result(symbol, criteria)
                    if result:
                        results.append(result)
            except Exception:  # noqa: BLE001
                continue
        results.sort(key=lambda x: x.signal_strength, reverse=True)
        return results[:limit]

    # --- Per-type scan logic -------------------------------------------------

    async def _scan_breakout(self, symbol: str) -> Optional[ScanResult]:
        """Stocks breaking out above resistance with rising volume."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0
        price = data["price"]

        if data.get("close") >= data.get("sma50", math.inf):
            criteria.append("Above SMA50")
            strength += 0.3
        if data.get("close", price) >= (data.get("52w_high", price) or price) * 0.96:
            criteria.append("Near 52-week high")
            strength += 0.25
        if data.get("volume_ratio", 0) >= 1.3:
            criteria.append(f"Volume {data['volume_ratio']:.1f}x avg")
            strength += 0.2
        rsi = data.get("rsi", 50)
        if 50 <= rsi <= 78:
            criteria.append(f"RSI {rsi:.0f}")
            strength += 0.15
        if data.get("close") > data.get("sma20", math.inf):
            strength += 0.1

        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_breakdown(self, symbol: str) -> Optional[ScanResult]:
        """Stocks breaking down below support with rising volume."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0

        if data.get("close") <= data.get("sma50", -math.inf):
            criteria.append("Below SMA50")
            strength += 0.3
        if data.get("close") <= (data.get("52w_low", data["price"]) or data["price"]) * 1.04:
            criteria.append("Near 52-week low")
            strength += 0.25
        if data.get("volume_ratio", 0) >= 1.3:
            criteria.append(f"Volume {data['volume_ratio']:.1f}x avg")
            strength += 0.2
        if data.get("rsi", 50) < 40:
            criteria.append(f"RSI {data['rsi']:.0f}")
            strength += 0.15
        if data.get("change_pct", 0) < 0:
            strength += 0.1

        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_momentum(self, symbol: str) -> Optional[ScanResult]:
        """Stocks with strong, sustained momentum."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0

        chg_1m = data.get("change_1m", 0)
        if chg_1m >= 8:
            criteria.append(f"1M gain {chg_1m:.1f}%")
            strength += 0.3
        elif chg_1m >= 3:
            criteria.append(f"1M gain {chg_1m:.1f}%")
            strength += 0.15
        chg_1w = data.get("change_1w", 0)
        if chg_1w >= 2:
            criteria.append(f"1W gain {chg_1w:.1f}%")
            strength += 0.2
        rsi = data.get("rsi", 50)
        if 55 <= rsi <= 75:
            criteria.append(f"RSI {rsi:.0f}")
            strength += 0.25
        if data.get("close") > data.get("sma20", math.inf):
            criteria.append("Above SMA20")
            strength += 0.15
        if data.get("macd_signal"):
            criteria.append("MACD positive")
            strength += 0.1

        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_volume_spike(self, symbol: str) -> Optional[ScanResult]:
        """Stocks with unusually high trading volume."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        ratio = data.get("volume_ratio", 0)
        if ratio < 1.8:
            return None
        criteria, strength = [], 0.0
        criteria.append(f"Volume {ratio:.1f}x avg")
        strength += min(ratio / 6, 0.7)
        if data.get("change_pct", 0) > 0:
            criteria.append("Up day")
            strength += 0.15
        elif data.get("change_pct", 0) < 0:
            criteria.append("Down day")
            strength += 0.15
        if data.get("rsi", 50) > 65:
            criteria.append("Overbought RSI")
            strength += 0.1
        return self._mk(symbol, data, criteria, strength)

    async def _scan_new_high(self, symbol: str) -> Optional[ScanResult]:
        """Stocks at or near their 52-week high."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        high52 = data.get("52w_high") or data["price"]
        if data.get("close", data["price"]) < high52 * 0.995:
            return None
        criteria, strength = [], 0.0
        criteria.append("52-week high")
        strength += 0.5
        if data.get("close") > data.get("sma50", math.inf):
            strength += 0.2
        if data.get("change_pct", 0) > 0:
            criteria.append("Up day")
            strength += 0.15
        if data.get("volume_ratio", 0) > 1:
            criteria.append(f"Volume {data['volume_ratio']:.1f}x avg")
            strength += 0.15
        return self._mk(symbol, data, criteria, strength)

    async def _scan_new_low(self, symbol: str) -> Optional[ScanResult]:
        """Stocks at or near their 52-week low."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        low52 = data.get("52w_low") or data["price"]
        if data.get("close", data["price"]) > low52 * 1.005:
            return None
        criteria, strength = [], 0.0
        criteria.append("52-week low")
        strength += 0.5
        if data.get("close") < data.get("sma50", -math.inf):
            strength += 0.2
        if data.get("change_pct", 0) < 0:
            criteria.append("Down day")
            strength += 0.15
        if data.get("volume_ratio", 0) > 1:
            criteria.append(f"Volume {data['volume_ratio']:.1f}x avg")
            strength += 0.15
        return self._mk(symbol, data, criteria, strength)

    async def _scan_gap_up(self, symbol: str) -> Optional[ScanResult]:
        """Stocks that gapped up at the open."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        gap = data.get("gap_pct", 0)
        if gap < 1.2:
            return None
        criteria, strength = [], 0.0
        criteria.append(f"Gap up {gap:.1f}%")
        strength += 0.5
        if data.get("change_pct", 0) > gap * 0.5:
            criteria.append("Holding gains")
            strength += 0.2
        if data.get("volume_ratio", 0) > 1:
            criteria.append(f"Volume {data['volume_ratio']:.1f}x avg")
            strength += 0.2
        return self._mk(symbol, data, criteria, strength)

    async def _scan_gap_down(self, symbol: str) -> Optional[ScanResult]:
        """Stocks that gapped down at the open."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        gap = data.get("gap_pct", 0)
        if gap > -1.2:
            return None
        criteria, strength = [], 0.0
        criteria.append(f"Gap down {gap:.1f}%")
        strength += 0.5
        if data.get("change_pct", 0) < gap * 0.5:
            criteria.append("Continued selling")
            strength += 0.2
        if data.get("volume_ratio", 0) > 1:
            criteria.append(f"Volume {data['volume_ratio']:.1f}x avg")
            strength += 0.2
        return self._mk(symbol, data, criteria, strength)

    async def _scan_value(self, symbol: str) -> Optional[ScanResult]:
        """Undervalued stocks on valuation multiples."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0
        pe = data.get("pe", None)
        if isinstance(pe, (int, float)) and 0 < pe < 15:
            criteria.append(f"P/E {pe:.1f}")
            strength += 0.3
        pb = data.get("pb", None)
        if isinstance(pb, (int, float)) and 0 < pb < 1.5:
            criteria.append(f"P/B {pb:.1f}")
            strength += 0.2
        div = data.get("dividend_yield", 0) or 0
        if div > 1:
            criteria.append(f"Yield {div:.1f}%")
            strength += 0.2
        if data.get("eps", 0) and data["eps"] > 0:
            criteria.append("Profitable")
            strength += 0.15
        de = data.get("debt_equity", None)
        if isinstance(de, (int, float)) and 0 <= de < 0.5:
            criteria.append("Low debt")
            strength += 0.15
        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_growth(self, symbol: str) -> Optional[ScanResult]:
        """High-growth companies on revenue/EPS/ROE."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0
        rev = data.get("revenue_growth", 0) or 0
        if rev > 15:
            criteria.append(f"Rev growth {rev:.1f}%")
            strength += 0.3
        eps_g = data.get("eps_growth", 0) or 0
        if eps_g > 15:
            criteria.append(f"EPS growth {eps_g:.1f}%")
            strength += 0.3
        roe = data.get("roe", 0) or 0
        if roe > 15:
            criteria.append(f"ROE {roe:.1f}%")
            strength += 0.2
        if data.get("change_3m", 0) or 0 > 10:
            criteria.append(f"3M gain {data['change_3m']:.1f}%")
            strength += 0.2
        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_strong_fundamentals(self, symbol: str) -> Optional[ScanResult]:
        """Stocks with broad fundamental strength."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0
        roe = data.get("roe", 0) or 0
        if roe > 15:
            criteria.append(f"ROE {roe:.1f}%")
            strength += 0.25
        margin = data.get("profit_margin", 0) or 0
        if margin > 0.1:
            criteria.append(f"Margins {margin:.0%}")
            strength += 0.25
        rev = data.get("revenue_growth", 0) or 0
        if rev > 10:
            criteria.append(f"Rev growth {rev:.1f}%")
            strength += 0.2
        pe = data.get("pe", None)
        if isinstance(pe, (int, float)) and 0 < pe < 30:
            criteria.append(f"P/E {pe:.1f}")
            strength += 0.15
        if data.get("close") > data.get("sma50", math.inf):
            strength += 0.15
        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_quality_stocks(self, symbol: str) -> Optional[ScanResult]:
        """High-quality compounders: strong ROE, margins, low leverage."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0
        roe = data.get("roe", 0) or 0
        if roe > 18:
            criteria.append(f"ROE {roe:.1f}%")
            strength += 0.3
        margin = data.get("profit_margin", 0) or 0
        if margin > 0.15:
            criteria.append(f"Margins {margin:.0%}")
            strength += 0.25
        de = data.get("debt_equity", None)
        if isinstance(de, (int, float)) and 0 <= de < 0.8:
            criteria.append("Low debt")
            strength += 0.2
        if data.get("eps", 0) and data["eps"] > 0:
            criteria.append("Profitable")
            strength += 0.15
        if isinstance(data.get("pe"), (int, float)) and 0 < data["pe"] < 40:
            strength += 0.1
        if strength >= 0.45:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_swing(self, symbol: str) -> Optional[ScanResult]:
        """Swing-trade candidates: oversold with reversal setup or low volatility."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0
        rsi = data.get("rsi", 50)
        if 30 <= rsi <= 45:
            criteria.append(f"RSI oversold {rsi:.0f}")
            strength += 0.3
        elif 55 <= rsi <= 70:
            criteria.append(f"RSI momentum {rsi:.0f}")
            strength += 0.2
        vol = data.get("volatility", 0)
        if vol < 0.02:
            criteria.append("Low volatility setup")
            strength += 0.25
        if data.get("close") < data.get("sma20", -math.inf):
            criteria.append("Near short-term support")
            strength += 0.2
        if data.get("volume_ratio", 0) >= 0.8:
            criteria.append("Adequate volume")
            strength += 0.15
        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_intraday(self, symbol: str) -> Optional[ScanResult]:
        """High-volatility, high-liquidity candidates for intraday."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0
        vol = data.get("volatility", 0)
        if vol > 0.02:
            criteria.append(f"Volatility {vol:.1%}")
            strength += 0.3
        ratio = data.get("volume_ratio", 0)
        if ratio > 1.2:
            criteria.append(f"Volume {ratio:.1f}x avg")
            strength += 0.3
        price = data["price"]
        if 20 < price < 20000:
            criteria.append("Tradeable price")
            strength += 0.2
        if abs(data.get("gap_pct", 0)) > 0.5:
            criteria.append(f"Gap {data['gap_pct']:.1f}%")
            strength += 0.2
        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    async def _scan_options(self, symbol: str) -> Optional[ScanResult]:
        """Option-ready underlyings: liquid, trending, with volatility to price."""
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        criteria, strength = [], 0.0
        if data.get("volume", 0) >= 1_000_000:
            criteria.append("Liquid underlying")
            strength += 0.3
        if data.get("close") > data.get("sma50", math.inf):
            criteria.append("Uptrend")
            strength += 0.25
        vol = data.get("volatility", 0)
        if 0.01 <= vol <= 0.04:
            criteria.append("Priced volatility")
            strength += 0.2
        rsi = data.get("rsi", 50)
        if 45 <= rsi <= 65:
            criteria.append(f"RSI {rsi:.0f}")
            strength += 0.15
        if strength >= 0.4:
            return self._mk(symbol, data, criteria, strength)
        return None

    def _get_scanner_function(self, scanner_type: ScannerType) -> Callable:
        scanners = {
            ScannerType.BREAKOUT: self._scan_breakout,
            ScannerType.BREAKDOWN: self._scan_breakdown,
            ScannerType.MOMENTUM: self._scan_momentum,
            ScannerType.VOLUME_SPIKE: self._scan_volume_spike,
            ScannerType.NEW_HIGH: self._scan_new_high,
            ScannerType.NEW_LOW: self._scan_new_low,
            ScannerType.GAP_UP: self._scan_gap_up,
            ScannerType.GAP_DOWN: self._scan_gap_down,
            ScannerType.STRONG_FUNDAMENTALS: self._scan_strong_fundamentals,
            ScannerType.VALUE_PICKS: self._scan_value,
            ScannerType.GROWTH_STOCKS: self._scan_growth,
            ScannerType.QUALITY_STOCKS: self._scan_quality_stocks,
            ScannerType.SWING_TRADE: self._scan_swing,
            ScannerType.INTRADAY: self._scan_intraday,
            ScannerType.OPTIONS_PLAY: self._scan_options,
        }
        return scanners.get(scanner_type, self._scan_breakout)

    # --- Data plumbing -------------------------------------------------------

    def _get_market_universe(self, market: str) -> List[str]:
        if self.universe:
            return list(self.universe)
        try:
            from app.services.data.universe import by_market

            symbols = [d["symbol"] for d in by_market(market) if not d.get("index")]
            if symbols:
                return symbols
        except Exception:  # noqa: BLE001
            pass
        return list(_DEFAULT_INDIA if market == "india" else _DEFAULT_US)

    async def _get_stock_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch real quote/history/fundamentals (cached per scan run)."""
        if symbol in self._cache:
            return self._cache[symbol]
        if not self.market_service:
            self._cache[symbol] = None
            return None

        data: Dict[str, Any] = {}
        try:
            try:
                quote = await self.market_service.get_quote(symbol, provider="yahoo") or {}
            except TypeError:
                quote = await self.market_service.get_quote(symbol) or {}
            try:
                history = await self.market_service.get_history(symbol, period="1y", provider="yahoo") or {}
            except TypeError:
                history = await self.market_service.get_history(symbol, period="1y") or {}
            try:
                fund = await self.market_service.get_fundamentals(symbol, provider="yahoo") or {}
            except TypeError:
                fund = await self.market_service.get_fundamentals(symbol) or {}
            except Exception:  # noqa: BLE001
                fund = {}
        except Exception:  # noqa: BLE001
            self._cache[symbol] = None
            return None

        candles = history.get("candles") or []
        closes = [c.get("close") for c in candles if isinstance(c.get("close"), (int, float))]
        if len(closes) < 30:
            self._cache[symbol] = None
            return None

        price = quote.get("price")
        if not isinstance(price, (int, float)) or price <= 0:
            price = closes[-1]
        data["symbol"] = symbol
        data["name"] = quote.get("name") or symbol
        data["price"] = float(price)
        data["currency"] = quote.get("currency") or "INR"
        data["volume"] = int(quote.get("volume") or 0)
        data["change_pct"] = float(quote.get("day_change_pct") or 0.0)

        data["close"] = float(closes[-1])
        prev_close = float(closes[-2]) if len(closes) >= 2 else data["close"]
        data["gap_pct"] = float((candles[-1].get("open") / prev_close - 1) * 100) if candles else 0.0
        highs = [float(c["high"]) for c in candles if isinstance(c.get("high"), (int, float))]
        lows = [float(c["low"]) for c in candles if isinstance(c.get("low"), (int, float))]
        volumes = [int(c.get("volume") or 0) for c in candles]
        data["52w_high"] = max(highs) if highs else data["close"]
        data["52w_low"] = min(lows) if lows else data["close"]

        closes_arr = np.asarray(closes, dtype=float)
        data["sma20"] = float(closes_arr[-20:].mean())
        data["sma50"] = float(closes_arr[-50:].mean()) if len(closes_arr) >= 50 else float(closes_arr[-20:].mean())
        data["rsi"] = self._calculate_rsi(closes_arr)
        data["macd_signal"] = bool(data["close"] > data["sma20"] > data["sma50"])
        data["change_1w"] = float((closes[-1] / closes[-6] - 1) * 100) if len(closes) >= 6 else 0.0
        data["change_1m"] = float((closes[-1] / closes[-21] - 1) * 100) if len(closes) >= 21 else 0.0
        data["change_3m"] = float((closes[-1] / closes[-63] - 1) * 100) if len(closes) >= 63 else 0.0
        if len(closes) >= 21:
            returns = np.diff(closes_arr[-21:]) / closes_arr[-21:-1]
            data["volatility"] = float(np.std(returns))
        else:
            data["volatility"] = 0.02
        avg_vol = float(np.mean(volumes[-20:])) if len(volumes) >= 5 else float(np.mean(volumes) or 1)
        data["avg_volume"] = int(avg_vol)
        data["volume_ratio"] = float(data["volume"] / avg_vol) if avg_vol > 0 else 0.0

        base = fund.get("base") or fund
        data["pe"] = base.get("trailingPE") or base.get("forwardPE")
        data["pb"] = base.get("priceToBook")
        data["roe"] = base.get("returnOnEquity")
        data["profit_margin"] = base.get("profitMargins")
        data["revenue_growth"] = (base.get("revenueGrowth") or 0) * 100
        data["eps_growth"] = (base.get("earningsGrowth") or 0) * 100
        data["dividend_yield"] = (base.get("dividendYield") or 0) * 100
        data["debt_equity"] = base.get("debtToEquity")
        data["eps"] = base.get("trailingEps")

        self._cache[symbol] = data
        return data

    def _mk(self, symbol: str, data: Dict[str, Any], criteria: List[str], strength: float) -> ScanResult:
        return ScanResult(
            symbol=symbol,
            name=data.get("name", symbol),
            price=data.get("price", 0),
            change_pct=data.get("change_pct", 0),
            volume=data.get("volume", 0),
            signal_strength=round(min(max(strength, 0), 1), 3),
            matched_criteria=criteria,
        )

    def _calculate_rsi(self, closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes[-(period + 1):])
        gains = deltas[deltas > 0].sum() / period
        losses = -deltas[deltas < 0].sum() / period
        if losses == 0:
            return 100.0
        rs = gains / losses
        return float(100 - (100 / (1 + rs)))

    # --- Custom criteria scanning -------------------------------------------

    async def _matches_criteria(self, symbol: str, criteria: Dict) -> bool:
        data = await self._get_stock_data(symbol)
        if not data:
            return False
        for key, condition in criteria.items():
            if key not in data:
                return False
            if not self._evaluate_condition(data[key], condition):
                return False
        return True

    def _evaluate_condition(self, value: Any, condition: Any) -> bool:
        if isinstance(condition, dict):
            op = condition.get("operator", "==")
            target = condition.get("value")
            if op == ">":
                return value > target
            if op == "<":
                return value < target
            if op == ">=":
                return value >= target
            if op == "<=":
                return value <= target
            if op == "!=":
                return value != target
            return value == target
        return value == condition

    async def _create_scan_result(self, symbol: str, criteria: Dict) -> Optional[ScanResult]:
        data = await self._get_stock_data(symbol)
        if not data:
            return None
        return ScanResult(
            symbol=symbol,
            name=data.get("name", symbol),
            price=data.get("price", 0),
            change_pct=data.get("change_pct", 0),
            volume=data.get("volume", 0),
            signal_strength=0.5,
            matched_criteria=[f"{k}: {v}" for k, v in criteria.items()],
        )
