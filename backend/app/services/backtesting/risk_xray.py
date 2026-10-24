"""Risk x-ray for a backtest: regime exposure, tail risk, underwater episodes,
turnover and a monthly-returns table — all computed from the actual run, none
fabricated."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _finite(x: float) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def risk_xray(
    equity: np.ndarray,
    returns: np.ndarray,
    positions: np.ndarray | None = None,
    dates=None,
) -> dict:
    eq = np.asarray(equity, dtype=float)
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]

    monthly = {}
    if dates is not None and len(dates) == len(eq):
        try:
            ts = pd.to_datetime(pd.Series(dates), errors="coerce")
            s = pd.Series(eq, index=ts.index)
            monthly_ret = (s.resample("ME").last() / s.resample("ME").last().shift(1) - 1).dropna()
            monthly = {
                str(idx.date()): _finite(float(v))
                for idx, v in monthly_ret.tail(12).items()
                if np.isfinite(v)
            }
        except Exception:  # noqa: BLE001 - never let a pretty table crash the x-ray
            monthly = {}

    n = len(r)
    vol = float(np.std(r, ddof=1)) if n > 1 else 0.0
    threshold = 2.0 * vol if vol > 0 else 0.0
    tail = float(np.mean(r < -threshold)) if n else 0.0

    max_consec_losses = 0
    cur = 0
    for x in r:
        if x < 0:
            cur += 1
            max_consec_losses = max(max_consec_losses, cur)
        else:
            cur = 0

    exposure = float(np.mean(positions > 0)) if positions is not None and len(positions) else 0.0
    turnover = 0.0
    if positions is not None and len(positions) > 1:
        turnover = float(np.mean(np.abs(np.diff(positions.astype(float))))) if positions.size > 1 else 0.0

    underwater = []
    if len(eq) > 1:
        peak = np.maximum.accumulate(eq)
        in_dd = False
        start = 0
        trough = eq[0]
        for i in range(len(eq)):
            if not in_dd and eq[i] < peak[i]:
                in_dd = True
                start = i
                trough = eq[i]
            elif in_dd:
                trough = min(trough, eq[i])
                if eq[i] >= peak[i] or i == len(eq) - 1:
                    in_dd = False
                    depth = (trough - peak[start]) / peak[start] if peak[start] else 0.0
                    underwater.append({
                        "start": _finite(peak[start]),
                        "end": _finite(peak[i]),
                        "depth": _finite(depth),
                        "start_index": start,
                        "end_index": i,
                    })
    underwater = sorted(underwater, key=lambda d: d["depth"])[:5]

    return {
        "exposure_time": _finite(exposure),
        "turnover_per_bar": _finite(turnover),
        "tail_risk_pct": _finite(tail * 100),
        "max_consecutive_losses": max_consec_losses,
        "worst_period_return": _finite(float(np.min(r))) if n else 0.0,
        "best_period_return": _finite(float(np.max(r))) if n else 0.0,
        "downside_deviation": _finite(float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)))) if n else 0.0,
        "underwater_episodes": underwater,
        "monthly_returns": monthly,
        "n_bars": n,
    }
