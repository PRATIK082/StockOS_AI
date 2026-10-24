"""Backtest engine v2 — bar-level fills with real cost modeling.

Fills happen at the *next* bar's open after a signal (no look-ahead): a
position held during bar ``i`` is decided from data up to the close of bar
``i-1``, executed at ``open[i]``, and the intra-bar return is split
(``open[i]/close[i-1]`` for the old position, ``close[i]/open[i]`` for the
new one). Costs (India stack by default, see ``costs.py``) are deducted from
traded notional on entry and exit. Metrics, risk x-ray, benchmark comparison
and optional walk-forward validation are all derived from that one equity
curve — nothing is fabricated or double-counted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.services.backtesting.costs import CostConfig, india_cost_config
from app.services.backtesting.metrics import compute_metrics, to_returns
from app.services.backtesting.risk_xray import risk_xray
from app.services.backtesting.sandbox import StrategySandboxError, run_user_strategy
from app.services.backtesting.strategies import STRATEGIES, StrategySpec, get_strategy
from app.services.backtesting.validation import (
    WalkForwardConfig,
    monte_carlo,
    bootstrap_metrics,
    walk_forward,
)
from app.services.data.ohlcv import sanitize_history, to_dataframe

DEFAULT_INTERVAL = "1d"
DEFAULT_PERIOD = "2y"


@dataclass
class BacktestRequest:
    symbol: str
    interval: str = DEFAULT_INTERVAL
    period: str = DEFAULT_PERIOD
    strategy: str = "moving_average_crossover"
    params: dict = field(default_factory=dict)
    initial_capital: float = 100_000.0
    costs: CostConfig | None = None
    benchmark_symbol: str | None = None
    validate: bool = False
    custom_code: str | None = None


def _resolved_params(spec: StrategySpec, params: dict | None) -> dict:
    """Keep only params the strategy actually declares.

    Defends against stale param keys leaking in from a previously selected
    strategy (e.g. ``k`` from Bollinger when running RSI), a hand-built CLI
    payload, or a scheduled playbook that kept old values.
    """
    allowed = set(spec.param_schema) | set(spec.default_params)
    if not allowed:
        return {}
    return {k: v for k, v in (params or {}).items() if k in allowed}


def build_positions(df: pd.DataFrame, request: BacktestRequest) -> pd.Series:
    """Produce the 0/1 position series for a request (built-in or custom)."""
    if request.custom_code and request.custom_code.strip():
        return run_user_strategy(request.custom_code, df, request.params)
    spec = get_strategy(request.strategy)
    if spec is None:
        raise ValueError(
            f"unknown strategy '{request.strategy}' (choose from {sorted(s.name for s in STRATEGIES.values())})"
        )
    params = {**spec.default_params, **_resolved_params(spec, request.params)}
    return spec.fn(df, **params)


def _equity_path(
    df: pd.DataFrame,
    positions: np.ndarray,
    initial_capital: float,
    costs: CostConfig,
) -> tuple[np.ndarray, list[dict]]:
    n = len(df)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    pos = positions.astype(float)
    equity = np.empty(n, dtype=float)
    equity[0] = initial_capital
    trades: list[dict] = []
    open_trade: dict | None = None
    buy_cost = costs.buy_cost_pct()
    sell_cost = costs.sell_cost_pct()
    for i in range(1, n):
        held_before = pos[i - 1]
        held_after = pos[i]
        r_open = open_[i] / close[i - 1] - 1 if close[i - 1] else 0.0
        r_intra = close[i] / open_[i] - 1 if open_[i] else 0.0
        port_ret = held_before * r_open + held_after * r_intra
        equity[i] = equity[i - 1] * (1 + port_ret)
        delta = held_after - held_before
        if abs(delta) > 1e-12:
            notional = equity[i] * abs(delta)
            cost = notional * (buy_cost if delta > 0 else sell_cost)
            equity[i] -= cost
            if delta > 0:
                open_trade = {"entry_index": i, "entry_price": open_[i], "qty": abs(delta)}
            elif open_trade is not None:
                holding = i - open_trade["entry_index"]
                gross_pct = open_[i] / open_trade["entry_price"] - 1
                pnl_pct = gross_pct - buy_cost - sell_cost
                trades.append({
                    "entry_index": open_trade["entry_index"],
                    "exit_index": i,
                    "entry_price": round(float(open_trade["entry_price"]), 6),
                    "exit_price": round(float(open_[i]), 6),
                    "holding_periods": holding,
                    "pnl_pct": round(float(pnl_pct), 6),
                    "pnl": round(float(equity[i] * pnl_pct), 4),
                })
                open_trade = None
    if open_trade is not None:  # mark-to-market at the final close
        i = n - 1
        gross_pct = close[i] / open_trade["entry_price"] - 1
        pnl_pct = gross_pct - buy_cost - sell_cost
        trades.append({
            "entry_index": open_trade["entry_index"],
            "exit_index": i,
            "entry_price": round(float(open_trade["entry_price"]), 6),
            "exit_price": round(float(close[i]), 6),
            "holding_periods": i - open_trade["entry_index"],
            "pnl_pct": round(float(pnl_pct), 6),
            "pnl": round(float(equity[i] * pnl_pct), 4),
            "open": True,
        })
    return equity, trades


def run_backtest(df: pd.DataFrame, request: BacktestRequest) -> dict:
    if df is None or df.empty:
        raise ValueError("no data for backtest")
    costs = request.costs or india_cost_config()
    positions = build_positions(df, request).astype(int).to_numpy()
    equity, trades = _equity_path(df, positions, request.initial_capital, costs)
    returns = to_returns(equity)
    metrics = compute_metrics(
        equity, returns,
        interval=request.interval or DEFAULT_INTERVAL,
        trades=trades,
        initial_capital=request.initial_capital,
    )
    risk = risk_xray(
        equity, returns, positions,
        dates=[str(d) for d in df.index],
    )
    result: dict = {
        "symbol": request.symbol,
        "interval": request.interval or DEFAULT_INTERVAL,
        "strategy": request.strategy,
        "params": request.params,
        "initial_capital": request.initial_capital,
        "dates": [str(d) for d in df.index],
        "equity": [round(float(x), 4) for x in equity],
        "positions": positions.astype(int).tolist(),
        "trades": trades,
        "metrics": metrics,
        "risk": risk,
        "cost_config": costs.as_dict(),
        "n_bars": len(df),
    }
    if request.validate and len(df) >= 60:
        result["monte_carlo"] = monte_carlo(returns, seed=42)
        result["bootstrap"] = bootstrap_metrics(returns, interval=request.interval or DEFAULT_INTERVAL, seed=42)

        def _pos_fn(slice_df: pd.DataFrame) -> pd.Series:
            if request.custom_code and request.custom_code.strip():
                return run_user_strategy(
                    request.custom_code, slice_df, request.params, use_subprocess=False
                )
            spec = get_strategy(request.strategy)
            params = {**spec.default_params, **_resolved_params(spec, request.params)}
            return spec.fn(slice_df, **params)

        result["walk_forward"] = walk_forward(
            _pos_fn, df, request.interval or DEFAULT_INTERVAL,
            WalkForwardConfig(folds=4, train_ratio=0.7),
        )
    return result


def run_backtest_with_benchmark(
    df: pd.DataFrame,
    bench_df: pd.DataFrame | None,
    request: BacktestRequest,
) -> dict:
    result = run_backtest(df, request)
    if bench_df is not None and len(bench_df) > 1:
        bd = bench_df["close"].to_numpy(dtype=float)
        bench_ret = bd[1:] / bd[:-1] - 1
        bench_eq = np.concatenate([[request.initial_capital], request.initial_capital * np.cumprod(1.0 + bench_ret)])
        result["benchmark"] = {
            "symbol": request.benchmark_symbol,
            "equity": [round(float(x), 4) for x in bench_eq],
            "total_return": round(float(bench_eq[-1] / request.initial_capital - 1), 6),
            "metrics": compute_metrics(bench_eq, to_returns(bench_eq), interval=request.interval or DEFAULT_INTERVAL),
            "end_value": round(float(bd[-1]), 4),
        }
    return result
