"""Quantitative risk analytics: parametric / Cornish-Fisher VaR, EWMA vol,
and peaks-over-threshold EVT (generalized Pareto tail) VaR + expected
shortfall. All results are finite-safe (NaN/empty inputs degrade to None/0.0
instead of crashing the caller). VaR is returned as a positive loss."""

from __future__ import annotations

import numpy as np

from app.services.backtesting.metrics import var_historical


def _clean(r: np.ndarray) -> np.ndarray:
    a = np.asarray(r, dtype=float)
    return a[np.isfinite(a)]


def parametric_var(returns: np.ndarray, level: float = 0.05, horizon: int = 1) -> dict:
    """Variance-covariance VaR: -mean + z*vol*sqrt(horizon) (positive loss)."""
    r = _clean(returns)
    if len(r) < 10:
        return {"error": "need at least 10 returns"}
    mean, std = float(r.mean()), float(r.std(ddof=1))
    if std <= 0:
        return {"var": 0.0, "level": level, "horizon": horizon, "mean": mean, "vol": 0.0}
    from scipy.stats import norm

    z = norm.ppf(level)
    var = -(mean + z * std * np.sqrt(horizon))
    return {
        "var": float(max(var, 0.0)),
        "es": float(max(-mean + std * norm.pdf(z) / level * np.sqrt(horizon), 0.0)),
        "level": level,
        "horizon": horizon,
        "mean": mean,
        "vol": std,
    }


def cornish_fisher_var(returns: np.ndarray, level: float = 0.05, horizon: int = 1) -> dict:
    """Cornish-Fisher VaR: normal quantile adjusted for skewness and kurtosis."""
    r = _clean(returns)
    if len(r) < 20:
        return {"error": "need at least 20 returns"}
    from scipy.stats import norm

    z = norm.ppf(level)
    mean, std = float(r.mean()), float(r.std(ddof=1))
    if std <= 0:
        return {"var": 0.0, "level": level, "horizon": horizon}
    s = float(r.skew()) if hasattr(r, "skew") else float(pd_skew(r))
    k = float(r.kurtosis()) if hasattr(r, "kurtosis") else float(pd_kurt(r))
    z_cf = z + (z**2 - 1) * s / 6 + (z**3 - 3 * z) * k / 24 - (2 * z**3 - 5 * z) * s**2 / 36
    var = -(mean + z_cf * std * np.sqrt(horizon))
    return {
        "var": float(max(var, 0.0)),
        "level": level,
        "horizon": horizon,
        "skewness": float(s),
        "excess_kurtosis": float(k),
    }


def _pd_skew(r: np.ndarray) -> float:
    m = r - r.mean()
    return float((np.mean(m**3)) / (np.mean(m**2) ** 1.5)) if np.mean(m**2) > 0 else 0.0


def _pd_kurt(r: np.ndarray) -> float:
    m = r - r.mean()
    v = np.mean(m**2)
    return float(np.mean(m**4) / v**2 - 3) if v > 0 else 0.0


pd_skew = _pd_skew
pd_kurt = _pd_kurt


def ewma_vol(returns: np.ndarray, lambda_: float = 0.94) -> dict:
    """EWMA volatility forecast (RiskMetrics-style), initialized with sample var."""
    r = _clean(returns)
    if len(r) < 5:
        return {"error": "need at least 5 returns"}
    if not (0 < lambda_ < 1):
        return {"error": "lambda must be in (0,1)"}
    var = float(np.var(r, ddof=1))
    for x in r:
        var = lambda_ * var + (1 - lambda_) * x**2
    return {"ewma_vol": float(np.sqrt(var)), "lambda": lambda_, "n": len(r)}


def _gpd_params(excesses: np.ndarray) -> tuple[float, float]:
    """Method-of-moments fit of a generalized Pareto distribution over
    excesses above a threshold. Returns (shape xi, scale beta)."""
    e = _clean(excesses)
    if len(e) < 10:
        return 0.0, 0.0
    m1, m2 = float(e.mean()), float(np.mean(e**2))
    denom = m2 - m1**2
    if denom <= 0 or m1 <= 0:
        return 0.0, float(m1)
    xi = 0.5 * m1**2 / denom - 0.5  # moment estimator
    beta = m1 * (1 - xi)
    if xi >= 1 or beta <= 0:
        return 0.0, float(m1)
    return float(xi), float(beta)


def evt_var(returns: np.ndarray, level: float = 0.05, threshold_pct: float = 0.95) -> dict:
    """Peaks-over-threshold EVT VaR/ES using a GPD tail (losses above the
    threshold quantile). Positive losses. ``level`` must be > ``1 - threshold_pct``."""
    r = _clean(returns)
    if len(r) < 50:
        return {"error": "need at least 50 returns"}
    if not (0 < 1 - threshold_pct < level < 1):
        return {"error": "need threshold_pct in (0,1) with level > 1 - threshold_pct"}
    u = float(np.quantile(r, threshold_pct))  # threshold on losses (positive)
    # Guarantee >=10 data points strictly above the threshold (data can be
    # discrete/heavy-tailed, where the requested quantile equals the max).
    for cand in reversed(np.sort(np.unique(r))):
        if int((r > cand).sum()) >= 10:
            u = min(u, float(cand))
            break
    excesses = r[r > u] - u
    xi, beta = _gpd_params(excesses)
    n = len(r)
    n_u = len(excesses)
    if n_u < 10:
        return {"error": "not enough exceedances above the threshold", "n_exceedances": int(n_u)}
    p = level
    ratio = n * (1 - p) / n_u
    if xi == 0:
        var = u + beta * np.log(ratio)
        es = (var + beta) if ratio > 0 else np.nan
    else:
        var = u + beta / xi * (ratio ** (-xi) - 1)
        es = (var + (beta - xi * u)) / (1 - xi)
    return {
        "var": float(max(var, 0.0)) if np.isfinite(var) else None,
        "es": float(max(es, var)) if np.isfinite(es) else None,
        "level": level,
        "threshold": float(u),
        "n_exceedances": int(n_u),
        "gpd_shape": float(xi),
        "gpd_scale": float(beta),
    }
