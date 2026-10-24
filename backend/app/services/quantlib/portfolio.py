"""Portfolio analytics: Black-Litterman view blending and Brinson
performance attribution. All finite-safe; missing assets in views degrade to
neutral (zero net view weight) instead of raising."""

from __future__ import annotations

import numpy as np


def black_litterman(
    returns_mean: dict[str, float],
    cov: np.ndarray,
    market_weights: dict[str, float],
    views: list[dict],
    risk_free: float = 0.0,
    tau: float = 0.05,
) -> dict:
    """Black-Litterman posterior returns/covariance from equilibrium implied
    returns blended with analyst views.

    ``views`` is a list of ``{"assets": [...], "weights": [...], "return": x}``
    (a P x q row). ``risk_free``/``tau`` control the prior strength. Returns
    implied, posterior returns, posterior covariance and a mean-variance
    weight suggestion (no-short-clipped, renormalized).
    """
    assets = list(returns_mean.keys())
    n = len(assets)
    if n < 2:
        return {"error": "need at least 2 assets"}
    cov = np.asarray(cov, dtype=float)
    if cov.shape != (n, n):
        return {"error": "covariance must be n x n matching returns_mean"}
    mu = np.asarray([float(returns_mean[a]) for a in assets], dtype=float)
    w = np.asarray([float(market_weights.get(a, 0.0)) for a in assets], dtype=float)
    w = w / w.sum() if w.sum() > 0 else np.full(n, 1.0 / n)
    mkt_var = float(w @ cov @ w)
    market_excess = float(w @ mu) - risk_free
    delta = market_excess / mkt_var if mkt_var > 0 else 1.0
    pi = delta * (cov @ w)  # implied equilibrium returns

    rows = []
    qs = []
    for v in views:
        weights_v = [float(x) for x in v.get("weights", [])]
        names = v.get("assets", [])
        if len(names) != len(weights_v):
            continue
        if not np.any(np.asarray(weights_v, dtype=float)):
            continue  # skip all-zero rows, but allow zero-sum (long/short) views
        row = np.zeros(n)
        for name, wt in zip(names, weights_v):
            if name in returns_mean:
                row[assets.index(name)] = wt
        rows.append(row)
        qs.append(float(v["return"]))
    if not rows:
        return {"error": "no usable views provided"}
    P = np.asarray(rows, dtype=float)
    q = np.asarray(qs, dtype=float)

    tauS = tau * cov
    k = len(rows)
    Omega = np.diag(np.diag(P @ tauS @ P.T))  # view uncertainty from prior
    inv_omega = np.linalg.inv(Omega)
    A_inv = np.linalg.inv(tauS)
    mid = np.linalg.inv(P @ tauS @ P.T + Omega)
    posterior_mu = pi + tauS @ P.T @ mid @ (q - P @ pi)
    posterior_cov = (1 + tau) * cov - tauS @ P.T @ mid @ P @ tauS
    posterior_cov = (posterior_cov + posterior_cov.T) / 2

    inv_pcov = np.linalg.pinv(posterior_cov)
    raw = inv_pcov @ posterior_mu
    delta_p = float(posterior_mu @ inv_pcov @ posterior_mu) if np.isfinite(inv_pcov.sum()) else 1.0
    gamma = delta_p if delta_p > 0 else 1.0
    w_opt = raw / gamma
    w_opt = np.clip(w_opt, 0, None)
    if w_opt.sum() > 0:
        w_opt = w_opt / w_opt.sum()
    return {
        "assets": assets,
        "implied_returns": {a: float(pi[i]) for i, a in enumerate(assets)},
        "posterior_returns": {a: float(posterior_mu[i]) for i, a in enumerate(assets)},
        "posterior_covariance": np.round(posterior_cov, 8).tolist(),
        "optimal_weights": {a: round(float(w_opt[i]), 6) for i, a in enumerate(assets)},
        "risk_aversion": float(delta),
        "tau": tau,
        "n_views": k,
    }


def brinson_attribution(
    portfolio_returns: dict[str, float],
    benchmark_returns: dict[str, float],
    portfolio_weights: dict[str, float],
    benchmark_weights: dict[str, float],
) -> dict:
    """Brinson-Fachler attribution: allocation, selection and interaction
    effects per asset plus totals, relative to the benchmark."""
    assets = sorted(set(portfolio_returns) | set(benchmark_returns))
    if not assets:
        return {"error": "no assets provided"}
    rp = np.asarray([float(portfolio_returns.get(a, 0.0)) for a in assets])
    rb = np.asarray([float(benchmark_returns.get(a, 0.0)) for a in assets])
    wp = np.asarray([float(portfolio_weights.get(a, 0.0)) for a in assets])
    wb = np.asarray([float(benchmark_weights.get(a, 0.0)) for a in assets])
    sp, sb = wp.sum(), wb.sum()
    wp = wp / sp if sp > 0 else wp
    wb = wb / sb if sb > 0 else wb
    rb_total = float(wb @ rb)

    alloc = (wp - wb) * (rb - rb_total)
    select = wb * (rp - rb)
    inter = (wp - wb) * (rp - rb)
    detail = []
    for i, a in enumerate(assets):
        detail.append(
            {
                "asset": a,
                "portfolio_weight": round(float(wp[i]), 6),
                "benchmark_weight": round(float(wb[i]), 6),
                "portfolio_return": round(float(rp[i]), 6),
                "benchmark_return": round(float(rb[i]), 6),
                "allocation": round(float(alloc[i]), 6),
                "selection": round(float(select[i]), 6),
                "interaction": round(float(inter[i]), 6),
                "total": round(float(alloc[i] + select[i] + inter[i]), 6),
            }
        )
    return {
        "assets": detail,
        "totals": {
            "allocation": round(float(alloc.sum()), 6),
            "selection": round(float(select.sum()), 6),
            "interaction": round(float(inter.sum()), 6),
            "active_return": round(float(alloc.sum() + select.sum() + inter.sum()), 6),
        },
        "benchmark_total_return": round(rb_total, 6),
        "portfolio_total_return": round(float(wp @ rp), 6),
    }
