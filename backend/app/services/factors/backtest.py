"""Factor portfolio backtest: rotate the symbol cross-section into the top
quantile of a signal each rebalance and measure the resulting equity curve
with the full metrics block (Sharpe/drawdown/etc). Rebalancing uses the
forward return realized on the following bar, so there is no look-ahead."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.backtesting.metrics import compute_metrics, to_returns

DEFAULT_CAPITAL = 100_000.0


def _quantile_membership(signal: pd.Series, n_quantiles: int) -> tuple[np.ndarray, np.ndarray]:
    """Boolean masks of the top (highest) and bottom (lowest) quantiles.

    NaN signals are excluded. Uses rank-percentile based splitting so duplicate
    signal values never collapse a bucket (``pd.qcut`` with ``duplicates="drop"``
    would silently drop bins and empty the top quantile).
    """
    valid = signal.notna().to_numpy(dtype=bool)
    top = np.zeros(len(signal), dtype=bool)
    bottom = np.zeros(len(signal), dtype=bool)
    if valid.sum() < 2:
        return top, bottom
    rank_pct = signal.iloc[valid].rank(pct=True).to_numpy(dtype=float)
    labels = np.floor(rank_pct * n_quantiles).astype(int)
    labels = np.clip(labels, 0, n_quantiles - 1)
    top[valid] = labels == n_quantiles - 1
    bottom[valid] = labels == 0
    return top, bottom


def factor_portfolio_backtest(
    panel: pd.DataFrame,
    signal_col: str,
    *,
    n_quantiles: int = 5,
    initial_capital: float = DEFAULT_CAPITAL,
    interval: str = "1d",
    long_only: bool = True,
) -> dict:
    """Daily-rebalanced equal-weight top-quantile (long-only) or long-short
    portfolio backtest over the panel. Returns equity, dates, metrics."""
    if panel.empty or signal_col not in panel.columns:
        raise ValueError("panel is empty or signal column missing")
    fwd = panel["fwd_return"]
    long_rets: list[float] = []
    short_rets: list[float] = []
    dates_out: list[str] = []
    for date, grp in panel.groupby(level=1):
        sig = grp[signal_col]
        top, bottom = _quantile_membership(sig, n_quantiles)
        rets = fwd.loc[grp.index].to_numpy(dtype=float)
        finite = np.isfinite(rets)
        top = top & finite
        bottom = bottom & finite
        has = top.sum() > 0
        hasb = bottom.sum() > 0
        if not has:
            continue
        long_rets.append(float(np.mean(rets[top])))
        dates_out.append(str(date.date()))
        if hasb:
            short_rets.append(float(np.mean(rets[bottom])))
    if len(long_rets) < 5:
        return {"error": "not enough rebalance dates for a portfolio backtest", "n_days": len(long_rets)}
    long_rets = np.asarray(long_rets)
    if long_only:
        port_ret = long_rets
    else:
        short_rets = np.asarray(short_rets)
        n = min(len(long_rets), len(short_rets))
        port_ret = long_rets[:n] - short_rets[:n]
    equity = np.concatenate([[initial_capital], initial_capital * np.cumprod(1 + port_ret)])
    metrics = compute_metrics(
        equity, to_returns(equity), interval=interval, initial_capital=initial_capital
    )
    return {
        "signal": signal_col,
        "n_quantiles": n_quantiles,
        "long_only": long_only,
        "initial_capital": initial_capital,
        "dates": dates_out,
        "daily_returns": [round(float(r), 8) for r in port_ret],
        "equity": [round(float(x), 4) for x in equity],
        "metrics": metrics,
        "n_days": len(port_ret),
    }
