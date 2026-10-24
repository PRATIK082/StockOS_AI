"""Performance / risk metrics for backtests and portfolios.

All functions are finite-safe: NaN / inf inputs become 0 or None so JSON
serialization never dies, matching the Vibe-Trading "strict-JSON finite-number"
discipline. Annualization uses a per-interval trading-periods-per-year table
(see ``app.services.data.ohlcv.annualization_factor``).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.services.data.ohlcv import annualization_factor


def _finite(x: float, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def to_returns(equity: np.ndarray | list[float]) -> np.ndarray:
    """Simple returns from an equity curve (first element dropped)."""
    eq = np.asarray(equity, dtype=float)
    if eq.size < 2:
        return np.array([], dtype=float)
    prev = eq[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = eq[1:] / prev - 1
    return np.where(np.isfinite(prev) & (prev != 0), ret, 0.0)


def annualized_return(total_return: float, n_periods: int, interval: str) -> float:
    """CAGR given the number of observed periods and the interval."""
    years = n_periods / annualization_factor(interval) if annualization_factor(interval) else 0
    if years <= 0:
        return 0.0
    return _finite((1 + total_return) ** (1 / years) - 1)


def sharpe_ratio(returns: np.ndarray, interval: str, risk_free: float = 0.0) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    std = float(np.std(r, ddof=1))
    if std <= 0 or not math.isfinite(std):
        return 0.0
    return _finite((float(np.mean(r)) - risk_free) / std * math.sqrt(annualization_factor(interval)))


def sortino_ratio(returns: np.ndarray, interval: str, risk_free: float = 0.0) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    downside = r[r < risk_free]
    if downside.size == 0:
        return 0.0
    dstd = float(np.sqrt(np.mean(downside ** 2)))
    if dstd <= 0 or not math.isfinite(dstd):
        return 0.0
    return _finite((float(np.mean(r)) - risk_free) / dstd * math.sqrt(annualization_factor(interval)))


def max_drawdown(equity: np.ndarray) -> float:
    """Maximum drawdown as a fraction (0..1), finite-safe."""
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak != 0, (eq - peak) / peak, 0.0)
    dd = np.nan_to_num(dd, nan=0.0, posinf=0.0, neginf=0.0)
    return float(-np.min(dd)) if dd.size else 0.0


def max_drawdown_duration_days(equity: np.ndarray, dates) -> int:
    """Longest underwater streak in days (0 when never underwater)."""
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0 or len(dates) != eq.size:
        return 0
    peak = np.maximum.accumulate(eq)
    under = eq < peak
    longest = 0
    cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    if longest == 0:
        return 0
    try:
        idx = pd.to_datetime(pd.Series(dates), errors="coerce")
        idx = idx.dropna()
        if idx.size < 2:
            return 0
        span = (idx.iloc[-1] - idx.iloc[0]).days
        return int(round(longest / max(idx.size, 1) * max(span, 1)))
    except Exception:  # noqa: BLE001
        return longest


def annualized_vol(returns: np.ndarray, interval: str) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    return _finite(float(np.std(r, ddof=1)) * math.sqrt(annualization_factor(interval)))


def calmar_ratio(total_return: float, n_periods: int, interval: str, mdd: float) -> float:
    ann = annualized_return(total_return, n_periods, interval)
    return _finite(ann / mdd) if mdd > 0 else 0.0


def var_historical(returns: np.ndarray, level: float = 0.05) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return 0.0
    return float(-np.nanpercentile(r, level * 100)) if np.isfinite(r).any() else 0.0


def cvar_historical(returns: np.ndarray, level: float = 0.05) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return 0.0
    threshold = np.percentile(r, level * 100)
    tail = r[r <= threshold]
    return float(-np.mean(tail)) if tail.size else 0.0


def skewness(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 3:
        return 0.0
    return _finite(float(pd.Series(r).skew()))


def kurtosis(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 4:
        return 0.0
    return _finite(float(pd.Series(r).kurtosis()))


def regression_stats(strategy_returns: np.ndarray, bench_returns: np.ndarray) -> dict:
    """Alpha / beta / correlation / tracking error vs a benchmark.

    Bench returns are reindexed to align with strategy returns by position; a
    length mismatch falls back to the overlapping tail.
    """
    s = np.asarray(strategy_returns, dtype=float)
    b = np.asarray(bench_returns, dtype=float)
    n = min(len(s), len(b))
    if n < 2:
        return {"alpha": 0.0, "beta": 0.0, "correlation": 0.0, "tracking_error": 0.0}
    s, b = s[-n:], b[-n:]
    s = s[np.isfinite(s)]
    b = b[np.isfinite(b)]
    n = min(len(s), len(b))
    if n < 2:
        return {"alpha": 0.0, "beta": 0.0, "correlation": 0.0, "tracking_error": 0.0}
    s, b = s[-n:], b[-n:]
    var_b = float(np.var(b, ddof=1))
    if var_b <= 0:
        beta = 1.0
    else:
        beta = float(np.cov(s, b, ddof=1)[0, 1] / var_b)
    te = float(np.std(s - b, ddof=1)) if n > 1 else 0.0
    corr = float(np.corrcoef(s, b)[0, 1]) if n > 1 else 0.0
    # Annualized alpha via the mean differential (period-agnostic when both
    # series share the same step size).
    alpha = float(np.mean(s) - beta * float(np.mean(b)))
    return {
        "alpha": _finite(alpha),
        "beta": _finite(beta),
        "correlation": _finite(corr),
        "tracking_error": _finite(te),
    }


def summarize_trades(trades: list) -> dict:
    """Trade-level statistics from a list of trade dicts (finite-safe)."""
    pnls = [_finite(t.get("pnl", 0.0)) for t in trades]
    if not trades:
        return {
            "total_trades": 0, "winning": 0, "losing": 0, "win_rate": 0.0,
            "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0, "avg_holding_periods": 0.0,
        }
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "total_trades": len(trades),
        "winning": len(wins),
        "losing": len(losses),
        "win_rate": len(wins) / len(trades),
        "profit_factor": _finite(gross_win / gross_loss) if gross_loss > 0 else (9.99 if gross_win > 0 else 0.0),
        "avg_win": _finite(float(np.mean(wins))) if wins else 0.0,
        "avg_loss": _finite(float(np.mean(losses))) if losses else 0.0,
        "best_trade": max(pnls),
        "worst_trade": min(pnls),
        "avg_holding_periods": _finite(float(np.mean([_finite(t.get("holding_periods", 0)) for t in trades]))),
    }


def compute_metrics(
    equity: np.ndarray,
    returns: np.ndarray,
    *,
    interval: str,
    trades: list | None = None,
    bench_returns: np.ndarray | None = None,
    initial_capital: float = 1.0,
) -> dict:
    """The full metrics block for a run (single source of truth for the API)."""
    eq = np.asarray(equity, dtype=float)
    n_periods = max(len(returns), 1)
    total_return = (eq[-1] / initial_capital - 1) if len(eq) and initial_capital else 0.0
    mdd = max_drawdown(eq)
    ann_ret = annualized_return(total_return, n_periods, interval)
    m: dict = {
        "initial_capital": _finite(initial_capital),
        "final_equity": _finite(eq[-1]) if len(eq) else 0.0,
        "total_return": _finite(total_return),
        "annualized_return": _finite(ann_ret),
        "annualized_vol": annualized_vol(returns, interval),
        "sharpe_ratio": sharpe_ratio(returns, interval),
        "sortino_ratio": sortino_ratio(returns, interval),
        "calmar_ratio": calmar_ratio(total_return, n_periods, interval, mdd),
        "max_drawdown": mdd,
        "var_95": var_historical(returns),
        "cvar_95": cvar_historical(returns),
        "skewness": skewness(returns),
        "kurtosis": kurtosis(returns),
        "n_periods": n_periods,
    }
    if trades is not None:
        m["trades"] = summarize_trades(trades)
    if bench_returns is not None:
        m["benchmark"] = regression_stats(returns, bench_returns)
    return m
