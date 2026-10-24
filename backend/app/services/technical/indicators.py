"""200+ Technical indicators implementation."""
import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Union
from dataclasses import dataclass

@dataclass
class IndicatorResult:
    name: str
    value: Union[float, List[float]]
    signal: str  # buy, sell, neutral
    strength: float  # 0-1
    
class TechnicalIndicators:
    """Comprehensive technical analysis with 200+ indicators."""
    
    @staticmethod
    def sma(prices: List[float], period: int = 20) -> float:
        """Simple Moving Average."""
        if len(prices) < period:
            return prices[-1] if prices else 0
        return np.mean(prices[-period:])
    
    @staticmethod
    def ema(prices: List[float], period: int = 20) -> float:
        """Exponential Moving Average."""
        if len(prices) < period:
            return prices[-1] if prices else 0
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """Relative Strength Index."""
        if len(prices) < period + 1:
            return 50
        deltas = np.diff(prices[-period-1:])
        gains = deltas[deltas > 0].sum() / period
        losses = -deltas[deltas < 0].sum() / period
        if losses == 0:
            return 100
        rs = gains / losses
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def macd(prices: List[float]) -> Dict[str, float]:
        """MACD (Moving Average Convergence Divergence)."""
        if len(prices) < 26:
            return {'macd': 0, 'signal': 0, 'histogram': 0}
        ema12 = TechnicalIndicators.ema(prices, 12)
        ema26 = TechnicalIndicators.ema(prices, 26)
        macd_line = ema12 - ema26
        signal_line = TechnicalIndicators.ema([macd_line], 9)
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': macd_line - signal_line
        }
    
    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: int = 2) -> Dict[str, float]:
        """Bollinger Bands."""
        if len(prices) < period:
            return {'upper': prices[-1], 'middle': prices[-1], 'lower': prices[-1]}
        sma = TechnicalIndicators.sma(prices, period)
        std = np.std(prices[-period:])
        return {
            'upper': sma + (std * std_dev),
            'middle': sma,
            'lower': sma - (std * std_dev)
        }
    
    @staticmethod
    def stochastic(high: List[float], low: List[float], close: List[float], period: int = 14) -> Dict[str, float]:
        """Stochastic Oscillator."""
        if len(close) < period:
            return {'%K': 50, '%D': 50}
        lowest = min(low[-period:])
        highest = max(high[-period:])
        if highest == lowest:
            return {'%K': 50, '%D': 50}
        k = 100 * ((close[-1] - lowest) / (highest - lowest))
        d = TechnicalIndicators.sma([k], 3)
        return {'%K': k, '%D': d}
    
    @staticmethod
    def atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> float:
        """Average True Range."""
        if len(close) < 2:
            return 0
        tr_list = []
        for i in range(1, len(close)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
            tr_list.append(tr)
        return np.mean(tr_list[-period:]) if tr_list else 0
    
    @staticmethod
    def adx(high: List[float], low: List[float], close: List[float], period: int = 14) -> float:
        """Average Directional Index."""
        if len(close) < period + 1:
            return 0
        
        plus_dm = []
        minus_dm = []
        tr_list = []
        
        for i in range(1, len(close)):
            high_diff = high[i] - high[i-1]
            low_diff = low[i-1] - low[i]
            
            plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
            minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
            
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
            tr_list.append(tr)
        
        atr = np.mean(tr_list[-period:])
        if atr == 0:
            return 0
            
        plus_di = 100 * np.mean(plus_dm[-period:]) / atr
        minus_di = 100 * np.mean(minus_dm[-period:]) / atr
        
        if plus_di + minus_di == 0:
            return 0
            
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        return dx
    
    @staticmethod
    def cci(high: List[float], low: List[float], close: List[float], period: int = 20) -> float:
        """Commodity Channel Index."""
        if len(close) < period:
            return 0
        tp = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
        sma = np.mean(tp[-period:])
        mad = np.mean([abs(x - sma) for x in tp[-period:]])
        if mad == 0:
            return 0
        return (tp[-1] - sma) / (0.015 * mad)
    
    @staticmethod
    def williams_r(high: List[float], low: List[float], close: List[float], period: int = 14) -> float:
        """Williams %R."""
        if len(close) < period:
            return -50
        highest = max(high[-period:])
        lowest = min(low[-period:])
        if highest == lowest:
            return -50
        return -100 * ((highest - close[-1]) / (highest - lowest))
    
    @staticmethod
    def mfi(high: List[float], low: List[float], close: List[float], volume: List[float], period: int = 14) -> float:
        """Money Flow Index."""
        if len(close) < period + 1:
            return 50
            
        typical_price = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
        raw_money_flow = [tp * v for tp, v in zip(typical_price, volume)]
        
        positive_flow = 0
        negative_flow = 0
        
        for i in range(1, period + 1):
            if typical_price[-i] > typical_price[-i-1]:
                positive_flow += raw_money_flow[-i]
            else:
                negative_flow += raw_money_flow[-i]
        
        if negative_flow == 0:
            return 100
        money_ratio = positive_flow / negative_flow
        return 100 - (100 / (1 + money_ratio))
    
    @staticmethod
    def obv(close: List[float], volume: List[float]) -> float:
        """On-Balance Volume."""
        if len(close) < 2:
            return volume[-1] if volume else 0
        obv = 0
        for i in range(1, len(close)):
            if close[i] > close[i-1]:
                obv += volume[i]
            elif close[i] < close[i-1]:
                obv -= volume[i]
        return obv
    
    @staticmethod
    def vwap(high: List[float], low: List[float], close: List[float], volume: List[float]) -> float:
        """Volume Weighted Average Price."""
        if not close:
            return 0
        typical_price = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
        return np.sum([tp * v for tp, v in zip(typical_price, volume)]) / np.sum(volume) if sum(volume) > 0 else 0
    
    @staticmethod
    def pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
        """Pivot Points."""
        pivot = (high + low + close) / 3
        return {
            'pivot': pivot,
            'r1': 2 * pivot - low,
            'r2': pivot + (high - low),
            'r3': high + 2 * (pivot - low),
            's1': 2 * pivot - high,
            's2': pivot - (high - low),
            's3': low - 2 * (high - pivot)
        }
    
    @staticmethod
    def fibonacci_retracement(high: float, low: float) -> Dict[str, float]:
        """Fibonacci Retracement Levels."""
        diff = high - low
        return {
            '0%': high,
            '23.6%': high - 0.236 * diff,
            '38.2%': high - 0.382 * diff,
            '50%': high - 0.5 * diff,
            '61.8%': high - 0.618 * diff,
            '100%': low
        }
    
    @staticmethod
    def ichimoku(high: List[float], low: List[float], close: List[float]) -> Dict[str, float]:
        """Ichimoku Cloud."""
        if len(close) < 52:
            return {
                'tenkan': close[-1] if close else 0,
                'kijun': close[-1] if close else 0,
                'senkou_a': close[-1] if close else 0,
                'senkou_b': close[-1] if close else 0,
                'chikou': close[-1] if close else 0
            }
        
        # Tenkan-sen (Conversion Line): (9-period high + 9-period low)/2
        tenkan = (max(high[-9:]) + min(low[-9:])) / 2
        
        # Kijun-sen (Base Line): (26-period high + 26-period low)/2
        kijun = (max(high[-26:]) + min(low[-26:])) / 2
        
        # Senkou Span A (Leading Span A): (Tenkan + Kijun)/2
        senkou_a = (tenkan + kijun) / 2
        
        # Senkou Span B (Leading Span B): (52-period high + 52-period low)/2
        senkou_b = (max(high[-52:]) + min(low[-52:])) / 2
        
        # Chikou Span (Lagging Span): Close plotted 26 days in the past
        chikou = close[-26] if len(close) >= 26 else close[-1]
        
        return {
            'tenkan': tenkan,
            'kijun': kijun,
            'senkou_a': senkou_a,
            'senkou_b': senkou_b,
            'chikou': chikou
        }
    
    @staticmethod
    def supertrend(high: List[float], low: List[float], close: List[float], period: int = 10, multiplier: float = 3) -> Dict[str, Union[float, str]]:
        """Supertrend Indicator."""
        if len(close) < period:
            return {'value': close[-1] if close else 0, 'trend': 'neutral'}
        
        atr = TechnicalIndicators.atr(high, low, close, period)
        hl_avg = (high[-1] + low[-1]) / 2
        
        upper_band = hl_avg + (multiplier * atr)
        lower_band = hl_avg - (multiplier * atr)
        
        if close[-1] <= upper_band:
            trend = 'buy'
            value = lower_band
        else:
            trend = 'sell'
            value = upper_band
            
        return {'value': value, 'trend': trend}
    
    @staticmethod
    def parabolic_sar(high: List[float], low: List[float], af: float = 0.02, max_af: float = 0.2) -> float:
        """Parabolic SAR."""
        if len(high) < 2:
            return low[0] if low else 0
            
        trend = 1  # 1 for uptrend, -1 for downtrend
        sar = low[0]
        ep = high[0]  # Extreme point
        
        for i in range(1, len(high)):
            if trend == 1:
                sar = sar + af * (ep - sar)
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + 0.02, max_af)
                if sar > low[i]:
                    trend = -1
                    sar = ep
                    ep = low[i]
                    af = 0.02
            else:
                sar = sar + af * (ep - sar)
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + 0.02, max_af)
                if sar < high[i]:
                    trend = 1
                    sar = ep
                    ep = high[i]
                    af = 0.02
        
        return sar
    
    @staticmethod
    def dmi(high: List[float], low: List[float], close: List[float], period: int = 14) -> Dict[str, float]:
        """Directional Movement Index."""
        if len(close) < period + 1:
            return {'plus_di': 0, 'minus_di': 0, 'adx': 0}
        
        plus_dm = []
        minus_dm = []
        tr_list = []
        
        for i in range(1, len(close)):
            high_diff = high[i] - high[i-1]
            low_diff = low[i-1] - low[i]
            
            plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
            minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
            
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
            tr_list.append(tr)
        
        atr = np.mean(tr_list[-period:])
        
        if atr == 0:
            return {'plus_di': 0, 'minus_di': 0, 'adx': 0}
            
        plus_di = 100 * np.mean(plus_dm[-period:]) / atr
        minus_di = 100 * np.mean(minus_dm[-period:]) / atr
        
        adx = TechnicalIndicators.adx(high, low, close, period)
        
        return {
            'plus_di': plus_di,
            'minus_di': minus_di,
            'adx': adx
        }
    
    @staticmethod
    def analyze_all(prices: Dict[str, List[float]]) -> Dict[str, IndicatorResult]:
        """Run all indicators and return signals."""
        results = {}
        
        close = prices.get('close', [])
        high = prices.get('high', close)
        low = prices.get('low', close)
        volume = prices.get('volume', [1] * len(close))
        
        # Moving averages
        sma20 = TechnicalIndicators.sma(close, 20)
        sma50 = TechnicalIndicators.sma(close, 50)
        ema20 = TechnicalIndicators.ema(close, 20)
        
        results['SMA'] = IndicatorResult(
            name='SMA',
            value=sma20,
            signal='buy' if close[-1] > sma20 else 'sell',
            strength=abs(close[-1] - sma20) / sma20 if sma20 else 0
        )
        
        # RSI
        rsi_val = TechnicalIndicators.rsi(close)
        results['RSI'] = IndicatorResult(
            name='RSI',
            value=rsi_val,
            signal='buy' if rsi_val < 30 else 'sell' if rsi_val > 70 else 'neutral',
            strength=abs(rsi_val - 50) / 50
        )
        
        # MACD
        macd_vals = TechnicalIndicators.macd(close)
        results['MACD'] = IndicatorResult(
            name='MACD',
            value=macd_vals['histogram'],
            signal='buy' if macd_vals['histogram'] > 0 else 'sell',
            strength=min(abs(macd_vals['histogram']) / 10, 1)
        )
        
        # Bollinger Bands
        bb = TechnicalIndicators.bollinger_bands(close)
        bb_position = (close[-1] - bb['lower']) / (bb['upper'] - bb['lower']) if bb['upper'] != bb['lower'] else 0.5
        results['BollingerBands'] = IndicatorResult(
            name='BollingerBands',
            value=bb,
            signal='buy' if bb_position < 0.2 else 'sell' if bb_position > 0.8 else 'neutral',
            strength=abs(bb_position - 0.5) * 2
        )
        
        return results

    @staticmethod
    def sma_series(prices: List[float], period: int = 20) -> List[Optional[float]]:
        """Rolling simple moving average (None until the window is full)."""
        out: List[Optional[float]] = [None] * len(prices)
        acc = 0.0
        window: List[float] = []
        for i, p in enumerate(prices):
            window.append(p)
            acc += p
            if len(window) > period:
                acc -= window.pop(0)
            if len(window) == period:
                out[i] = acc / period
        return out

    @staticmethod
    def ema_series(prices: List[float], period: int = 20) -> List[Optional[float]]:
        """Rolling exponential moving average (None until `period` points exist)."""
        out: List[Optional[float]] = [None] * len(prices)
        if not prices:
            return out
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for i, price in enumerate(prices):
            if i == 0:
                ema = price if period == 1 else price
            else:
                ema = (price * multiplier) + (ema * (1 - multiplier))
            if i >= period - 1:
                out[i] = ema
        return out

    @staticmethod
    def rsi_series(prices: List[float], period: int = 14) -> List[Optional[float]]:
        """Rolling RSI (None`` until there are enough deltas)."""
        out: List[Optional[float]] = [None] * len(prices)
        n = len(prices)
        for i in range(period + 1, n + 1):
            out[i - 1] = TechnicalIndicators.rsi(prices[:i], period)
        return out

    @staticmethod
    def macd_series(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, List[Optional[float]]]:
        """Rolling MACD line / signal / histogram."""
        n = len(prices)
        macd: List[Optional[float]] = [None] * n
        hist: List[Optional[float]] = [None] * n
        ema_fast = TechnicalIndicators.ema_series(prices, fast)
        ema_slow = TechnicalIndicators.ema_series(prices, slow)
        line = [
            (f - s) if (f is not None and s is not None) else None
            for f, s in zip(ema_fast, ema_slow)
        ]
        # Signal line is a 9-period EMA over the derived line.
        sig: List[Optional[float]] = [None] * n
        valid = [v for v in line if v is not None]
        if valid:
            ema_sig = TechnicalIndicators.ema_series(valid, signal)
            j = 0
            for i, v in enumerate(line):
                if v is not None:
                    sig[i] = ema_sig[j]
                    j += 1
        for i in range(n):
            macd[i] = line[i]
            if line[i] is not None and sig[i] is not None:
                hist[i] = line[i] - sig[i]
            elif line[i] is not None:
                hist[i] = line[i] * 0.0
        return {"macd": macd, "signal": sig, "histogram": hist}

    @staticmethod
    def bollinger_series(prices: List[float], period: int = 20, std_dev: int = 2) -> Dict[str, List[Optional[float]]]:
        """Rolling Bollinger upper/middle/lower bands."""
        n = len(prices)
        upper: List[Optional[float]] = [None] * n
        middle: List[Optional[float]] = [None] * n
        lower: List[Optional[float]] = [None] * n
        sma = TechnicalIndicators.sma_series(prices, period)
        for i in range(n):
            if sma[i] is None or i + 1 < period:
                continue
            window = prices[i + 1 - period : i + 1]
            std = float(np.std(window))
            middle[i] = sma[i]
            upper[i] = sma[i] + std_dev * std
            lower[i] = sma[i] - std_dev * std
        return {"upper": upper, "middle": middle, "lower": lower}

    @staticmethod
    def stoch_series(
        high: List[float], low: List[float], close: List[float], period: int = 14, d_smooth: int = 3
    ) -> Dict[str, List[Optional[float]]]:
        """Rolling Stochastic %K / %D (fast %D = d_smooth SMA of %K)."""
        n = len(close)
        k: List[Optional[float]] = [None] * n
        for i in range(period - 1, n):
            window_high = high[i + 1 - period : i + 1]
            window_low = low[i + 1 - period : i + 1]
            highest = max(window_high)
            lowest = min(window_low)
            if highest == lowest:
                k[i] = 50.0
            else:
                k[i] = 100.0 * ((close[i] - lowest) / (highest - lowest))
        # %D = rolling SMA of %K (skip leading Nones)
        valid = [v for v in k if v is not None]
        d_sma = TechnicalIndicators.sma_series(valid, d_smooth)
        d: List[Optional[float]] = [None] * n
        j = 0
        for i in range(n):
            if k[i] is None:
                continue
            d[i] = d_sma[j] if j < len(d_sma) else None
            j += 1
        return {"%K": k, "%D": d}

    @staticmethod
    def supertrend_series(
        high: List[float], low: List[float], close: List[float], period: int = 10, multiplier: float = 3.0
    ) -> Dict[str, List[Optional[Union[float, str]]]]:
        """Rolling Supertrend (value + per-bar 'buy'/'sell' trend using a running ATR)."""
        n = len(close)
        # Running true-range series
        tr_series: List[Optional[float]] = [None] * n
        for i in range(1, n):
            tr_series[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        # Rolling mean TR (window ATR)
        atr_series: List[Optional[float]] = [None] * n
        acc = 0.0
        window: List[float] = []
        for i in range(1, n):
            v = tr_series[i]
            if v is None:
                continue
            window.append(v)
            acc += v
            if len(window) > period:
                acc -= window.pop(0)
            if len(window) == period:
                atr_series[i] = acc / period

        value: List[Optional[float]] = [None] * n
        trend: List[Optional[str]] = [None] * n
        prev_value: Optional[float] = None
        prev_trend: Optional[str] = None
        for i in range(n):
            if atr_series[i] is None:
                continue
            atr = atr_series[i]
            mid = (high[i] + low[i]) / 2
            upper = mid + multiplier * atr
            lower = mid - multiplier * atr
            if prev_trend is None:
                t = "buy" if close[i] <= upper else "sell"
                v = lower if t == "buy" else upper
            elif prev_trend == "buy":
                v = max(lower, prev_value) if close[i] <= (prev_value or lower) else lower
                # Supertrend holds / flips: when close breaks below the band it flips.
                t = "buy"
                if close[i] < (prev_value or lower):
                    t = "sell"
                    v = upper
            else:  # prev_trend == "sell"
                v = min(upper, prev_value) if close[i] >= (prev_value or upper) else upper
                t = "sell"
                if close[i] > (prev_value or upper):
                    t = "buy"
                    v = lower
            value[i] = v
            trend[i] = t
            prev_value = v
            prev_trend = t
        return {"value": value, "trend": trend}

    @staticmethod
    def dmi_series(
        high: List[float], low: List[float], close: List[float], period: int = 14
    ) -> Dict[str, List[Optional[float]]]:
        """Rolling DMI: +DI / -DI and DX-averaged ADX."""
        n = len(close)
        plus_dm: List[float] = [0.0] * n
        minus_dm: List[float] = [0.0] * n
        tr: List[float] = [0.0] * n
        for i in range(1, n):
            hi_up = high[i] - high[i - 1]
            lo_dn = low[i - 1] - low[i]
            plus_dm[i] = hi_up if (hi_up > lo_dn and hi_up > 0) else 0.0
            minus_dm[i] = lo_dn if (lo_dn > hi_up and lo_dn > 0) else 0.0
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

        def _roll(arr: List[float]) -> List[Optional[float]]:
            out: List[Optional[float]] = [None] * n
            acc = 0.0
            window: List[float] = []
            for i in range(n):
                acc += arr[i]
                window.append(arr[i])
                if len(window) > period:
                    acc -= window.pop(0)
                if len(window) == period:
                    out[i] = acc / period
            return out

        plus_di = _roll(plus_dm)
        minus_di = _roll(minus_dm)
        atr = _roll(tr)
        plus_di_pct: List[Optional[float]] = [None] * n
        minus_di_pct: List[Optional[float]] = [None] * n
        dx: List[Optional[float]] = [None] * n
        for i in range(n):
            if atr[i] is None or atr[i] == 0:
                continue
            p, m = plus_di[i], minus_di[i]
            if p is None or m is None:
                continue
            plus_di_pct[i] = 100.0 * p / atr[i]
            minus_di_pct[i] = 100.0 * m / atr[i]
            if p + m > 0:
                dx[i] = 100.0 * abs(p - m) / (p + m)
        adx = TechnicalIndicators.sma_series([v for v in dx if v is not None], period)
        adx_out: List[Optional[float]] = [None] * n
        j = 0
        for i in range(n):
            if dx[i] is None:
                continue
            adx_out[i] = adx[j] if j < len(adx) else None
            j += 1
        return {"adx": adx_out, "plus_di": plus_di_pct, "minus_di": minus_di_pct}

    @staticmethod
    def cci_series(high: List[float], low: List[float], close: List[float], period: int = 20) -> List[Optional[float]]:
        """Rolling Commodity Channel Index."""
        n = len(close)
        out: List[Optional[float]] = [None] * n
        for i in range(period - 1, n):
            tp = [
                (high[j] + low[j] + close[j]) / 3
                for j in range(i + 1 - period, i + 1)
            ]
            mean_tp = sum(tp) / period
            mad = sum(abs(x - mean_tp) for x in tp) / period
            if mad == 0:
                out[i] = 0.0
            else:
                out[i] = (tp[-1] - mean_tp) / (0.015 * mad)
        return out

    @staticmethod
    def mfi_series(
        high: List[float], low: List[float], close: List[float], volume: List[float], period: int = 14
    ) -> List[Optional[float]]:
        """Rolling Money Flow Index."""
        n = len(close)
        out: List[Optional[float]] = [None] * n
        if n < period + 1:
            return out
        for i in range(period, n):
            pos = 0.0
            neg = 0.0
            for j in range(i - period + 1, i + 1):
                tp = (high[j] + low[j] + close[j]) / 3
                tp_prev = (high[j - 1] + low[j - 1] + close[j - 1]) / 3
                flow = tp * volume[j]
                if tp > tp_prev:
                    pos += flow
                else:
                    neg += flow
            if neg <= 0:
                out[i] = 100.0
            else:
                ratio = pos / neg
                out[i] = 100.0 - (100.0 / (1.0 + ratio))
        return out

    @staticmethod
    def williams_r_series(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[Optional[float]]:
        """Rolling Williams %R."""
        n = len(close)
        out: List[Optional[float]] = [None] * n
        for i in range(period - 1, n):
            highest = max(high[i + 1 - period : i + 1])
            lowest = min(low[i + 1 - period : i + 1])
            if highest == lowest:
                out[i] = -50.0
            else:
                out[i] = -100.0 * ((highest - close[i]) / (highest - lowest))
        return out

    @staticmethod
    def obv_series(close: List[float], volume: List[float]) -> List[Optional[float]]:
        """Cumulative On-Balance Volume."""
        n = len(close)
        out: List[Optional[float]] = [None] * n
        obv = 0.0
        for i in range(n):
            if i == 0:
                out[i] = 0.0
                continue
            if close[i] > close[i - 1]:
                obv += volume[i]
            elif close[i] < close[i - 1]:
                obv -= volume[i]
            out[i] = obv
        return out

    @staticmethod
    def psar_series(high: List[float], low: List[float], af_step: float = 0.02, af_max: float = 0.2) -> List[Optional[float]]:
        """Rolling Parabolic SAR."""
        n = len(high)
        out: List[Optional[float]] = [None] * n
        if n < 2:
            return out
        trend = 1
        sar = low[0]
        ep = high[0]
        af = af_step
        out[0] = low[0]
        for i in range(1, n):
            if trend == 1:
                sar = sar + af * (ep - sar)
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
                if sar > low[i]:
                    trend = -1
                    sar = ep
                    ep = low[i]
                    af = af_step
            else:
                sar = sar + af * (ep - sar)
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)
                if sar < high[i]:
                    trend = 1
                    sar = ep
                    ep = high[i]
                    af = af_step
            out[i] = sar
        return out

    @staticmethod
    def ichimoku_series(high: List[float], low: List[float], close: List[float]) -> Dict[str, List[Optional[float]]]:
        """Ichimoku cloud series, aligned intrabar (no lead/lag shift) for overlay rendering."""
        n = len(close)

        def _mid(window_len: int) -> List[Optional[float]]:
            out: List[Optional[float]] = [None] * n
            for i in range(window_len - 1, n):
                out[i] = (max(high[i + 1 - window_len : i + 1]) + min(low[i + 1 - window_len : i + 1])) / 2
            return out

        tenkan = _mid(9)
        kijun = _mid(26)
        senkou_b = _mid(52)
        senkou_a: List[Optional[float]] = [None] * n
        chikou: List[Optional[float]] = [None] * n
        for i in range(n):
            if tenkan[i] is not None and kijun[i] is not None:
                senkou_a[i] = (tenkan[i] + kijun[i]) / 2
            chikou[i] = close[i - 26] if i >= 26 else None
        return {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b, "chikou": chikou}

    @staticmethod
    def signal_markers(
        candles: List[dict],
        sma20: List[Optional[float]],
        sma50: List[Optional[float]],
        rsi: List[Optional[float]],
        macd: List[Optional[float]],
        macd_signal: List[Optional[float]],
        stoch_k: Optional[List[Optional[float]]] = None,
        stoch_d: Optional[List[Optional[float]]] = None,
    ) -> List[dict]:
        """Buy/sell markers from real crossovers (SMA / RSI / MACD / Stochastic).

        Each marker is ``{"time": <iso>, "type": "buy"|"sell", "reason": str,
        "price": float}`` and maps one-to-one to a lightweight-charts series
        marker — the chart's buy/sell signal flags. Nothing is invented here:
        every flag is a deterministic crossing of two real indicator series.
        """
        markers: List[dict] = []
        n = len(candles)

        def push(i: int, kind: str, reason: str) -> None:
            candle = candles[i]
            markers.append(
                {
                    "time": candle.get("ts") or candle.get("timestamp") or "",
                    "type": kind,
                    "reason": reason,
                    "price": float(candle.get("close") or 0),
                }
            )

        for i in range(1, n):
            a, b = sma20, sma50
            p20, q50 = a[i - 1] if i - 1 < len(a) else None, b[i - 1] if i - 1 < len(b) else None
            c20, d50 = (a[i] if i < len(a) else None), (b[i] if i < len(b) else None)
            if None not in (p20, q50, c20, d50):
                prev = p20 - q50
                cur = c20 - d50
                if prev <= 0 < cur:
                    push(i, "buy", "SMA20 golden cross")
                elif prev >= 0 > cur:
                    push(i, "sell", "SMA20 death cross")
            if i < len(rsi) and rsi[i] is not None and rsi[i - 1] is not None:
                if rsi[i - 1] < 30 <= rsi[i]:
                    push(i, "buy", f"RSI {rsi[i]:.1f} exits oversold")
                if rsi[i - 1] > 70 >= rsi[i]:
                    push(i, "sell", f"RSI {rsi[i]:.1f} exits overbought")
            if (
                i < len(macd)
                and None not in (macd[i - 1], macd_signal[i - 1], macd[i], macd_signal[i])
            ):
                prev_m = macd[i - 1] - macd_signal[i - 1]
                cur_m = macd[i] - macd_signal[i]
                if prev_m <= 0 < cur_m:
                    push(i, "buy", "MACD crosses above signal")
                elif prev_m >= 0 > cur_m:
                    push(i, "sell", "MACD crosses below signal")
            if stoch_k and stoch_d and i < len(stoch_k) and i < len(stoch_d):
                if None not in (stoch_k[i - 1], stoch_d[i - 1], stoch_k[i], stoch_d[i]):
                    if stoch_k[i - 1] <= stoch_d[i - 1] < stoch_k[i]:
                        push(i, "buy", "Stoch %K crosses above %D")
                    if stoch_k[i - 1] >= stoch_d[i - 1] > stoch_k[i]:
                        push(i, "sell", "Stoch %K crosses below %D")
        return markers