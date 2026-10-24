"""Cashflow analytics: NPV, IRR, XIRR (day-count exact, annualized)."""

from __future__ import annotations

import numpy as np


def npv(rate: float, amounts: list[float]) -> float:
    """Net present value of a cashflow series; amounts[0] is period 0."""
    r = np.asarray(amounts, dtype=float)
    if r.size == 0:
        return 0.0
    t = np.arange(r.size, dtype=float)
    return float(np.sum(r / (1 + rate) ** t))


def irr(amounts: list[float], guess: float = 0.1, max_iter: int = 200) -> float:
    """Internal rate of return via Newton's method (bracket-guarded)."""
    r = np.asarray(amounts, dtype=float)
    if r.size == 0:
        return 0.0
    if (r > 0).all() or (r < 0).all():
        raise ValueError("IRR needs at least one sign change")
    rate = guess
    for _ in range(max_iter):
        denom = (1 + rate) ** np.arange(r.size, dtype=float)
        f = float(np.sum(r / denom))
        fp = float(np.sum(-np.arange(r.size, dtype=float) * r / (1 + rate) ** (np.arange(r.size, dtype=float) + 1)))
        if abs(f) < 1e-8:
            return float(rate)
        if not np.isfinite(fp) or fp == 0:
            break
        step = f / fp
        rate -= step
        if rate <= -1:
            rate = (rate + step) / 2 - 0.5 if rate <= -1 else -0.99
        if not np.isfinite(rate):
            raise ValueError("IRR did not converge")
    if not (-1 < rate < 2):
        raise ValueError("IRR did not converge to a reasonable rate")
    return float(rate)


def xirr(amounts: list[float], dates: list[str], guess: float = 0.1) -> float:
    """Exact-date IRR. ``dates`` are ISO ``YYYY-MM-DD``; returns the annualized
    rate that zeroes the NPV."""
    if len(amounts) != len(dates) or len(amounts) == 0:
        raise ValueError("amounts and dates must be equal-length non-empty")
    import datetime as dt

    d0 = dt.date.fromisoformat(dates[0])
    t = np.asarray(
        [(dt.date.fromisoformat(d) - d0).days / 365.0 for d in dates], dtype=float
    )
    r = np.asarray(amounts, dtype=float)
    if (r > 0).all() or (r < 0).all():
        raise ValueError("XIRR needs at least one sign change")

    rate = guess
    for _ in range(300):
        f = float(np.sum(r / (1 + rate) ** t))
        fp = float(np.sum(-t * r / (1 + rate) ** (t + 1)))
        if abs(f) < 1e-8:
            return float(rate)
        if not np.isfinite(fp) or fp == 0:
            break
        new_rate = rate - f / fp
        if not np.isfinite(new_rate) or new_rate <= -1:
            new_rate = (rate - 1) / 2
        if abs(new_rate - rate) < 1e-9:
            rate = new_rate
            break
        rate = new_rate
    if not (-1 < rate < 5):
        raise ValueError("XIRR did not converge")
    return float(rate)
