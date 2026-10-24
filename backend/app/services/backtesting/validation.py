"""Robustness validation: Monte Carlo, bootstrap, and walk-forward.

These are distributional sanity checks on top of a real backtest, not fake
safety. Everything is seeded (reproducible), finite-safe, and reported as
plain statistics a user can reason about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from app.services.backtesting.metrics import compute_metrics, max_drawdown, to_returns

PositionFn = Callable[[pd.DataFrame], pd.Series]


def _finite(x: float) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def monte_carlo(
    returns: np.ndarray,
    n_simulations: int = 1000,
    horizon: int | None = None,
    seed: int | None = None,
) -> dict:
    """Resample the observed return sequence (with replacement) and report the
    distribution of terminal wealth and max drawdown under the same length."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return {"error": "no returns to simulate", "n_simulations": n_simulations}
    horizon = horizon or len(r)
    rng = np.random.default_rng(seed)
    terminals = np.empty(n_simulations)
    drawdowns = np.empty(n_simulations)
    for i in range(n_simulations):
        sample = rng.choice(r, size=horizon, replace=True)
        equity = np.concatenate([[1.0], np.cumprod(1.0 + sample)])
        terminals[i] = equity[-1]
        drawdowns[i] = max_drawdown(equity)
    return {
        "n_simulations": n_simulations,
        "horizon": horizon,
        "terminal_median": _finite(np.median(terminals)),
        "terminal_p5": _finite(np.percentile(terminals, 5)),
        "terminal_p95": _finite(np.percentile(terminals, 95)),
        "terminal_prob_loss": _finite(float(np.mean(terminals < 1.0))),
        "max_drawdown_median": _finite(float(np.median(drawdowns))),
        "max_drawdown_p95": _finite(float(np.percentile(drawdowns, 95))),
        "max_drawdown_worst": _finite(float(np.max(drawdowns))),
    }


def bootstrap_metrics(
    returns: np.ndarray,
    n_iterations: int = 1000,
    interval: str = "1d",
    seed: int | None = None,
) -> dict:
    """Bootstrap confidence intervals for Sharpe / Sortino / vol / CAGR."""
    from app.services.backtesting.metrics import (  # local import to avoid a circular chain
        annualized_return,
        annualized_vol,
        sharpe_ratio,
        sortino_ratio,
    )

    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 4:
        return {"error": "not enough returns to bootstrap", "n_iterations": n_iterations}
    rng = np.random.default_rng(seed)
    col = {"sharpe": [], "sortino": [], "vol": [], "cagr": []}
    for _ in range(n_iterations):
        sample = rng.choice(r, size=len(r), replace=True)
        total = float(np.prod(1.0 + sample) - 1.0)
        col["sharpe"].append(sharpe_ratio(sample, interval))
        col["sortino"].append(sortino_ratio(sample, interval))
        col["vol"].append(annualized_vol(sample, interval))
        col["cagr"].append(annualized_return(total, len(sample), interval))
    out: dict = {"n_iterations": n_iterations}
    for key, values in col.items():
        arr = np.asarray(values)
        out[key] = {
            "median": _finite(np.median(arr)),
            "p5": _finite(np.percentile(arr, 5)),
            "p95": _finite(np.percentile(arr, 95)),
        }
    return out


@dataclass
class WalkForwardConfig:
    folds: int = 5
    train_ratio: float = 0.7
    anchored: bool = False  # True = growing train window, False = rolling window


def _equity_from_positions(df: pd.DataFrame, positions: pd.Series) -> np.ndarray:
    close = df["close"].astype(float)
    ret = close.pct_change().fillna(0.0).to_numpy()
    pos = positions.reindex(df.index).fillna(0).shift(1).fillna(0).to_numpy()
    return np.concatenate([[1.0], np.cumprod(1.0 + pos * ret)])


def walk_forward(
    positions_fn: PositionFn,
    df: pd.DataFrame,
    interval: str,
    config: WalkForwardConfig | None = None,
) -> dict:
    """K-fold walk-forward: strategy fitted/trained on each train window, then
    scored strictly out-of-sample on the following test window."""
    cfg = config or WalkForwardConfig()
    n = len(df)
    if n < 30:
        return {"error": "not enough bars for walk-forward", "bars": n}
    train_len = int(n * cfg.train_ratio)
    if train_len < 20 or cfg.folds < 2:
        return {"error": "walk-forward needs more data or fewer folds", "bars": n}
    remaining = n - train_len
    step = max(1, remaining // cfg.folds)
    folds_out = []
    for i in range(cfg.folds):
        start_train = 0 if cfg.anchored else i * step
        end_train = min(n, train_len + i * step)
        start_test = end_train
        end_test = min(n, start_test + step)
        if end_train - start_train < 20 or end_test - start_test < 5:
            break
        train_df = df.iloc[start_train:end_train]
        test_df = df.iloc[start_test:end_test]
        train_pos = positions_fn(train_df)
        test_pos = positions_fn(test_df)
        train_metrics = compute_metrics(
            _equity_from_positions(train_df, train_pos),
            to_returns(_equity_from_positions(train_df, train_pos)),
            interval=interval,
            initial_capital=1.0,
        )
        test_metrics = compute_metrics(
            _equity_from_positions(test_df, test_pos),
            to_returns(_equity_from_positions(test_df, test_pos)),
            interval=interval,
            initial_capital=1.0,
        )
        folds_out.append({
            "fold": i + 1,
            "train_rows": [start_train, end_train],
            "test_rows": [start_test, end_test],
            "train_metrics": {k: _finite(v) if isinstance(v, (int, float)) else v for k, v in train_metrics.items()},
            "test_metrics": {k: _finite(v) if isinstance(v, (int, float)) else v for k, v in test_metrics.items()},
        })
    if not folds_out:
        return {"error": "walk-forward produced no valid folds", "bars": n}

    def _avg(key: str, metric_key: str) -> float:
        vals = [_finite(f[key][metric_key]) for f in folds_out]
        return float(np.mean(vals)) if vals else 0.0

    return {
        "folds": folds_out,
        "n_folds": len(folds_out),
        "anchored": cfg.anchored,
        "avg_test_sharpe": _avg("test_metrics", "sharpe_ratio"),
        "avg_test_return": _avg("test_metrics", "total_return"),
        "avg_test_max_drawdown": _avg("test_metrics", "max_drawdown"),
        "avg_train_sharpe": _avg("train_metrics", "sharpe_ratio"),
        "overfit_gap": _avg("train_metrics", "sharpe_ratio") - _avg("test_metrics", "sharpe_ratio"),
    }
