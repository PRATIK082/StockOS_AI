"""Built-in strategy presets for the backtest engine.

Every strategy is a pure function ``(df: pd.DataFrame) -> pd.Series`` of target
positions in {0, 1} aligned to ``df.index``. Signals are computed from the full
history but the engine shifts them forward one bar before acting, so there is
no look-ahead bias (you enter at the *next* open after a signal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

StrategyFn = Callable[..., pd.Series]


@dataclass
class StrategySpec:
    name: str
    display_name: str
    description: str
    fn: StrategyFn
    default_params: dict = field(default_factory=dict)
    param_schema: dict = field(default_factory=dict)


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def moving_average_crossover(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    f = _sma(df["close"], fast)
    sl = _sma(df["close"], slow)
    return (f > sl).astype(int)


def rsi_mean_reversion(
    df: pd.DataFrame,
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    exit_level: float = 50.0,
) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs.fillna(100))
    pos = pd.Series(0, index=df.index)
    in_pos = False
    values = rsi.fillna(exit_level).to_numpy()
    out = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        if not in_pos and values[i] <= oversold:
            in_pos = True
        elif in_pos and values[i] >= exit_level:
            in_pos = False
        out[i] = 1 if in_pos else 0
    return pd.Series(out, index=df.index)


def bollinger_breakout(df: pd.DataFrame, period: int = 20, k: float = 2.0) -> pd.Series:
    mid = _sma(df["close"], period)
    std = df["close"].rolling(period, min_periods=1).std(ddof=0).fillna(0)
    upper = mid + k * std
    lower = mid - k * std
    pos = pd.Series(0, index=df.index)
    in_pos = False
    c = df["close"].to_numpy()
    up = upper.to_numpy()
    lo = lower.to_numpy()
    out = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        if not in_pos and c[i] > up[i]:
            in_pos = True
        elif in_pos and c[i] < mid.to_numpy()[i]:
            in_pos = False
        out[i] = 1 if in_pos else 0
    return pd.Series(out, index=df.index)


def donchian_breakout(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    high = df["high"].rolling(lookback, min_periods=1).max()
    low = df["low"].rolling(lookback, min_periods=1).min()
    pos = pd.Series(0, index=df.index)
    in_pos = False
    c = df["close"].to_numpy()
    h = high.to_numpy()
    lo = low.to_numpy()
    out = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        if not in_pos and i > 0 and c[i] > h[i - 1]:
            in_pos = True
        elif in_pos and i > 0 and c[i] < lo[i - 1]:
            in_pos = False
        out[i] = 1 if in_pos else 0
    return pd.Series(out, index=df.index)


def macd_trend(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    macd = _ema(df["close"], fast) - _ema(df["close"], slow)
    sig = macd.ewm(span=signal, adjust=False).mean()
    return (macd > sig).astype(int)


def buy_and_hold(df: pd.DataFrame, **_params) -> pd.Series:
    return pd.Series(1, index=df.index)


def momentum_trading(df: pd.DataFrame, ema_fast: int = 9, ema_slow: int = 21, rsi_period: int = 14, volume_mult: float = 1.5) -> pd.Series:
    """Strategy 1: Momentum Trading (Intraday)
    - Timeframe: 5-minute and 15-minute candles
    - Indicators: EMA(9), EMA(21), RSI(14), Volume, VWAP
    - Entry: Price crosses above EMA(9) + RSI > 55 + Volume > 1.5x average
    - Exit: RSI > 75 (overbought) or price closes below EMA(9)
    - Stop-loss: 0.5% below entry or recent swing low
    - Target: 1:2 risk-reward ratio minimum
    """
    import pandas as pd
    import numpy as np

    ema_fast_val = _ema(df["close"], ema_fast)
    ema_slow_val = _ema(df["close"], ema_slow)
    rsi = _calculate_rsi(df["close"], rsi_period)

    # Average volume for comparison
    avg_volume = df["volume"].rolling(20, min_periods=1).mean()
    vol_ratio = df["volume"] / avg_volume

    pos = pd.Series(0, index=df.index)
    in_pos = False
    entry_price = pd.Series(np.nan, index=df.index)
    c = df["close"].to_numpy()
    e_fast = ema_fast_val.to_numpy()
    e_slow = ema_slow_val.to_numpy()
    r = rsi.fillna(50).to_numpy()
    v = vol_ratio.to_numpy()

    for i in range(1, len(df)):
        if not in_pos:
            # Entry: price crosses above EMA(9) + RSI > 55 + Volume > 1.5x average
            if c[i] > e_fast[i] and r[i] > 55 and v[i] > volume_mult:
                in_pos = True
                entry_price.iloc[i] = c[i]
        else:
            # Exit: RSI > 75 (overbought) or price closes below EMA(9)
            if r[i] > 75 or c[i] < e_fast[i]:
                in_pos = False
                entry_price.iloc[i] = np.nan
        pos.iloc[i] = 1 if in_pos else 0

    return pos


def _calculate_rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_val = 100 - 100 / (1 + rs.fillna(100))
    return rsi_val


def mean_reversion(df: pd.DataFrame, period: int = 14, oversold: float = 30.0, overbought: float = 70.0, exit_level: float = 50.0) -> pd.Series:
    """Strategy 2: Mean Reversion (Intraday)
    - Timeframe: 15-minute candles
    - Indicators: Bollinger Bands(20, 2), RSI(14), Stochastic(14, 3, 3)
    - Entry: Price touches lower BB + RSI < 30 + Stochastic < 20
    - Exit: Price reaches middle BB or RSI > 50
    - Stop-loss: 1% below entry
    - Target: Upper BB or 1.5% gain
    """
    import pandas as pd
    import numpy as np

    # Bollinger Bands
    mid = _sma(df["close"], 20)
    std = df["close"].rolling(20, min_periods=1).std(ddof=0).fillna(0)
    upper = mid + 2.0 * std
    lower = mid - 2.0 * std

    # RSI
    rsi = _calculate_rsi(df["close"], period)

    # Stochastic %K
    low_min = df["low"].rolling(14, min_periods=1).min()
    high_max = df["high"].rolling(14, min_periods=1).max()
    stoch_k = ((df["close"] - low_min) / (high_max - low_min) * 100).fillna(50)

    pos = pd.Series(0, index=df.index)
    in_pos = False
    entry_price = pd.Series(np.nan, index=df.index)
    m = mid.to_numpy()
    u = upper.to_numpy()
    l = lower.to_numpy()
    r = rsi.fillna(50).to_numpy()
    k = stoch_k.fillna(50).to_numpy()
    c = df["close"].to_numpy()

    for i in range(1, len(df)):
        if not in_pos:
            # Entry: Price touches lower BB + RSI < 30 + Stochastic < 20
            if c[i] < l[i] and r[i] < oversold and k[i] < 20:
                in_pos = True
                entry_price.iloc[i] = c[i]
        else:
            # Exit: Price reaches middle BB or RSI > 50
            if c[i] >= m[i] or r[i] > exit_level:
                in_pos = False
                entry_price.iloc[i] = np.nan
        pos.iloc[i] = 1 if in_pos else 0

    return pos


def options_selling(df: pd.DataFrame, option_type: str = "strangle", delta: float = 0.15, max_lots: int = 4) -> pd.Series:
    """Strategy 3: Options Selling (Weekly)
    - Instruments: NIFTY and BANKNIFTY weekly options
    - Strategy: Iron Condor / Strangle with delta hedging
    - Entry: 9:45 AM IST on expiry day, sell OTM calls and puts (10-15 delta)
    - Exit: 3:00 PM IST or 50% profit achieved
    - Stop-loss: Combined premium doubles or underlying moves 1.5%
    - Position Size: Maximum 4 lots per strategy
    """
    import pandas as pd
    import numpy as np

    # For options selling, we use price action as proxy
    # Entry: price at recent high (overbought condition for selling)
    # This is a simplified version - full options selling requires option chain data
    sma_20 = _sma(df["close"], 20)
    sma_50 = _ema(df["close"], 50)
    rsi = _calculate_rsi(df["close"], 14)

    pos = pd.Series(0, index=df.index)
    in_pos = False
    c = df["close"].to_numpy()
    r = rsi.fillna(50).to_numpy()

    for i in range(1, len(df)):
        if not in_pos:
            # Entry: RSI overbought (sell opportunity) - simplified
            if r[i] > 70:
                in_pos = True
        else:
            # Exit: RSI oversold or significant price decline
            if r[i] < 30 or (i > 0 and c[i] < c[i-1] * 0.97):
                in_pos = False
        pos.iloc[i] = 1 if in_pos else 0

    return pos


def breakout_trading(df: pd.DataFrame, atr_period: int = 14, volume_mult: float = 2.0, lookback: int = 1) -> pd.Series:
    """Strategy 4: Breakout Trading
    - Timeframe: 30-minute and 1-hour candles
    - Indicators: ATR(14), Volume, Support/Resistance levels
    - Entry: Price breaks previous day high/low with volume > 2x average
    - Exit: Close below breakout level or ATR-based target
    - Stop-loss: Below breakout candle low (for long) or above high (for short)
    """
    import pandas as pd
    import numpy as np

    # Rolling high/low for breakout
    high_roll = df["high"].rolling(lookback + 1, min_periods=1).max()
    low_roll = df["low"].rolling(lookback + 1, min_periods=1).min()

    # ATR for volatility
    tr1 = df["high"] - df["low"]
    tr2 = abs(df["high"] - df["close"].shift())
    tr3 = abs(df["low"] - df["close"].shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(atr_period, min_periods=1).mean()

    # Average volume
    avg_vol = df["volume"].rolling(20, min_periods=1).mean()
    vol_ratio = df["volume"] / avg_vol

    pos = pd.Series(0, index=df.index)
    in_pos = False
    entry_price = pd.Series(np.nan, index=df.index)
    h = high_roll.to_numpy()
    l = low_roll.to_numpy()
    a = atr.to_numpy()
    v = vol_ratio.to_numpy()
    c = df["close"].to_numpy()

    for i in range(1, len(df)):
        if not in_pos:
            # Entry: Price breaks previous day high/low with volume > 2x average
            if (c[i] > h[i-1] or c[i] < l[i-1]) and v[i] > volume_mult:
                in_pos = True
                entry_price.iloc[i] = c[i]
        else:
            # Exit: Close below breakout level (for long) or above high (for short)
            # Simplified: exit if price moves against by ATR-based amount
            if c[i] < c[i-1] - a[i] or c[i] > c[i-1] + a[i]:
                in_pos = False
                entry_price.iloc[i] = np.nan
        pos.iloc[i] = 1 if in_pos else 0

    return pos


def trend_following(df: pd.DataFrame, sma_fast: int = 50, sma_slow: int = 200, macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9, adx_period: int = 15, adx_threshold: float = 25.0) -> pd.Series:
    """Strategy 5: Trend Following (Positional)
    - Timeframe: Daily candles
    - Indicators: SMA(50), SMA(200), MACD(12, 26, 9), ADX(14)
    - Entry: SMA(50) crosses above SMA(200) + MACD positive + ADX > 25
    - Exit: SMA(50) crosses below SMA(200) or MACD turns negative
    - Stop-loss: 8% below entry or recent swing low
    - Target: 20-30% or trend reversal signals
    """
    import pandas as pd
    import numpy as np

    # SMA indicators
    sma_f = _sma(df["close"], sma_fast)
    sma_s = _sma(df["close"], sma_slow)

    # MACD
    macd_line = _ema(df["close"], macd_fast) - _ema(df["close"], macd_slow)
    macd_signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal_line

    # ADX (simplified: +DM and -DM)
    plus_dm = df["high"].diff()
    minus_dm = df["low"].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    tr1 = df["high"] - df["low"]
    tr2 = abs(df["high"] - df["close"].shift())
    tr3 = abs(df["low"] - df["close"].shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(adx_period, min_periods=1).mean()
    plus_di = 100 * (plus_dm.rolling(adx_period, min_periods=1).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(adx_period, min_periods=1).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx

    pos = pd.Series(0, index=df.index)
    in_pos = False
    entry_price = pd.Series(np.nan, index=df.index)
    s_f = sma_f.to_numpy()
    s_s = sma_s.to_numpy()
    m = macd_line.fillna(0).to_numpy()
    h = macd_hist.fillna(0).to_numpy()
    a = adx.fillna(25).to_numpy()
    c = df["close"].to_numpy()

    for i in range(1, len(df)):
        if not in_pos:
            # Entry: SMA(50) crosses above SMA(200) + MACD positive + ADX > 25
            if s_f[i] > s_s[i] and m[i] > 0 and a[i] > adx_threshold:
                in_pos = True
                entry_price.iloc[i] = c[i]
        else:
            # Exit: SMA(50) crosses below SMA(200) or MACD turns negative
            if s_f[i] < s_s[i] or m[i] < 0:
                in_pos = False
                entry_price.iloc[i] = np.nan
        pos.iloc[i] = 1 if in_pos else 0

    return pos


STRATEGIES: dict[str, StrategySpec] = {
    "moving_average_crossover": StrategySpec(
        name="moving_average_crossover",
        display_name="Moving Average Crossover",
        description="Long when the fast SMA is above the slow SMA; exit below.",
        fn=moving_average_crossover,
        default_params={"fast": 20, "slow": 50},
        param_schema={"fast": {"type": "int", "min": 2, "max": 200, "step": 1},
                      "slow": {"type": "int", "min": 5, "max": 400, "step": 1}},
    ),
    "rsi_mean_reversion": StrategySpec(
        name="rsi_mean_reversion",
        display_name="RSI Mean Reversion",
        description="Buy oversold, exit when RSI recovers to the exit level.",
        fn=rsi_mean_reversion,
        default_params={"period": 14, "oversold": 30.0, "overbought": 70.0, "exit_level": 50.0},
        param_schema={"period": {"type": "int", "min": 2, "max": 100, "step": 1},
                      "oversold": {"type": "float", "min": 5, "max": 50, "step": 1},
                      "overbought": {"type": "float", "min": 50, "max": 95, "step": 1},
                      "exit_level": {"type": "float", "min": 5, "max": 95, "step": 1}},
    ),
    "bollinger_breakout": StrategySpec(
        name="bollinger_breakout",
        display_name="Bollinger Breakout",
        description="Long when price breaks above the upper band; exit at the middle band.",
        fn=bollinger_breakout,
        default_params={"period": 20, "k": 2.0},
        param_schema={"period": {"type": "int", "min": 5, "max": 100, "step": 1},
                      "k": {"type": "float", "min": 1.0, "max": 4.0, "step": 0.1}},
    ),
    "donchian_breakout": StrategySpec(
        name="donchian_breakout",
        display_name="Donchian Breakout",
        description="Classic turtle-style breakout of a rolling high/low channel.",
        fn=donchian_breakout,
        default_params={"lookback": 20},
        param_schema={"lookback": {"type": "int", "min": 5, "max": 200, "step": 1}},
    ),
    "macd_trend": StrategySpec(
        name="macd_trend",
        display_name="MACD Trend",
        description="Long when the MACD line is above its signal line.",
        fn=macd_trend,
        default_params={"fast": 12, "slow": 26, "signal": 9},
        param_schema={"fast": {"type": "int", "min": 2, "max": 100, "step": 1},
                      "slow": {"type": "int", "min": 5, "max": 200, "step": 1},
                      "signal": {"type": "int", "min": 2, "max": 50, "step": 1}},
    ),
    "buy_and_hold": StrategySpec(
        name="buy_and_hold",
        display_name="Buy & Hold",
        description="Always fully invested. The baseline every strategy is compared against.",
        fn=buy_and_hold,
        default_params={},
        param_schema={},
    ),
    "momentum_trading": StrategySpec(
        name="momentum_trading",
        display_name="Momentum Trading",
        description="EMA crossover + RSI + Volume momentum strategy (intraday).",
        fn=momentum_trading,
        default_params={"ema_fast": 9, "ema_slow": 21, "rsi_period": 14, "volume_mult": 1.5},
        param_schema={
            "ema_fast": {"type": "int", "min": 2, "max": 50, "step": 1},
            "ema_slow": {"type": "int", "min": 5, "max": 200, "step": 1},
            "rsi_period": {"type": "int", "min": 2, "max": 50, "step": 1},
            "volume_mult": {"type": "float", "min": 1.0, "max": 3.0, "step": 0.1},
        },
    ),
    "mean_reversion": StrategySpec(
        name="mean_reversion",
        display_name="Mean Reversion",
        description="Bollinger + RSI + Stochastic mean reversion strategy (intraday).",
        fn=mean_reversion,
        default_params={"period": 14, "oversold": 30.0, "overbought": 70.0, "exit_level": 50.0},
        param_schema={
            "period": {"type": "int", "min": 2, "max": 100, "step": 1},
            "oversold": {"type": "float", "min": 5, "max": 50, "step": 1},
            "overbought": {"type": "float", "min": 50, "max": 95, "step": 1},
            "exit_level": {"type": "float", "min": 5, "max": 95, "step": 1},
        },
    ),
    "options_selling": StrategySpec(
        name="options_selling",
        display_name="Options Selling",
        description="Iron condor/strangle selling strategy (weekly options).",
        fn=options_selling,
        default_params={"option_type": "strangle", "delta": 0.15, "max_lots": 4},
        param_schema={
            "option_type": {"type": "str", "enum": ["strangle", "iron_condor"]},
            "delta": {"type": "float", "min": 0.05, "max": 0.3, "step": 0.01},
            "max_lots": {"type": "int", "min": 1, "max": 10, "step": 1},
        },
    ),
    "breakout_trading": StrategySpec(
        name="breakout_trading",
        display_name="Breakout Trading",
        description="ATR + volume breakout strategy (30-min/1-hr candles).",
        fn=breakout_trading,
        default_params={"atr_period": 14, "volume_mult": 2.0, "lookback": 1},
        param_schema={
            "atr_period": {"type": "int", "min": 5, "max": 50, "step": 1},
            "volume_mult": {"type": "float", "min": 1.0, "max": 5.0, "step": 0.1},
            "lookback": {"type": "int", "min": 1, "max": 60, "step": 1},
        },
    ),
    "trend_following": StrategySpec(
        name="trend_following",
        display_name="Trend Following",
        description="SMA crossover + MACD + ADX trend-following strategy (positional).",
        fn=trend_following,
        default_params={"sma_fast": 50, "sma_slow": 200, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "adx_period": 15, "adx_threshold": 25.0},
        param_schema={
            "sma_fast": {"type": "int", "min": 5, "max": 100, "step": 1},
            "sma_slow": {"type": "int", "min": 20, "max": 400, "step": 1},
            "macd_fast": {"type": "int", "min": 2, "max": 50, "step": 1},
            "macd_slow": {"type": "int", "min": 10, "max": 100, "step": 1},
            "macd_signal": {"type": "int", "min": 2, "max": 20, "step": 1},
            "adx_period": {"type": "int", "min": 5, "max": 50, "step": 1},
            "adx_threshold": {"type": "float", "min": 5, "max": 50, "step": 0.5},
        },
    ),
}


def get_strategy(name: str) -> StrategySpec | None:
    return STRATEGIES.get(name)


def list_strategies() -> list[dict]:
    return [
        {
            "name": s.name,
            "display_name": s.display_name,
            "description": s.description,
            "default_params": s.default_params,
            "param_schema": s.param_schema,
        }
        for s in STRATEGIES.values()
    ]
