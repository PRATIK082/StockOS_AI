"""Deterministic portfolio optimizers.

``returns`` is a DataFrame of per-period returns, columns = assets. Five
methods: EqualWeight, MinVariance, MaxSharpe, RiskParity (equal risk
contribution) and InverseVol. All are closed-form / fixed-iteration — no
external optimizer dependency — finite-safe, and no-short by default
(negative weights are clipped and renormalized, which is disclosed in the
result metadata rather than hidden).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class PortfolioResult:
    method: str
    weights: dict[str, float]
    expected_annual_return: float
    expected_annual_vol: float
    sharpe: float
    n_assets: int
    notes: list[str] = None

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "weights": self.weights,
            "expected_annual_return": self.expected_annual_return,
            "expected_annual_vol": self.expected_annual_vol,
            "sharpe": self.sharpe,
            "n_assets": self.n_assets,
            "notes": self.notes or [],
        }


METHODS = ["equal_weight", "min_variance", "max_sharpe", "risk_parity", "inverse_vol"]


def _finite(x: float) -> float:
    try:
        v = float(x)
        return v if np.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_weights(w: np.ndarray, names: list[str]) -> dict[str, float]:
    w = np.nan_to_num(np.asarray(w, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    if w.sum() <= 0:
        w = np.full(len(w), 1.0 / max(len(w), 1))
    return {names[i]: round(_finite(w[i]), 6) for i in range(len(w))}


def _cov(returns: pd.DataFrame) -> np.ndarray:
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna(how="all", axis=1).fillna(0.0)
    if clean.empty or clean.shape[1] < 1:
        raise ValueError("no usable return series for optimization")
    n = len(clean)
    if n < 2:
        raise ValueError("need at least 2 periods to estimate covariance")
    return np.atleast_2d(clean.cov().to_numpy())


def _mean(returns: pd.DataFrame) -> np.ndarray:
    clean = returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return np.asarray(clean.mean().to_numpy(), dtype=float)


def equal_weight(returns: pd.DataFrame) -> PortfolioResult:
    names = list(returns.columns)
    w = np.full(len(names), 1.0 / max(len(names), 1))
    return _finalize("equal_weight", names, w, returns)


def inverse_vol(returns: pd.DataFrame) -> PortfolioResult:
    names = list(returns.columns)
    vols = np.nan_to_num(returns.std().to_numpy(), nan=1.0)
    vols = np.where(vols <= 0, 1.0, vols)
    w = 1.0 / vols
    return _finalize("inverse_vol", names, w, returns)


def min_variance(returns: pd.DataFrame, _risk_free: float = 0.0) -> PortfolioResult:
    names = list(returns.columns)
    S = _cov(returns)
    n = len(names)
    ones = np.ones(n)
    try:
        inv = np.linalg.inv(S + np.eye(n) * 1e-10)
        w = inv @ ones / (ones @ inv @ ones)
    except np.linalg.LinAlgError:  # pragma: no cover - defensive
        w = np.full(n, 1.0 / n)
    w = np.maximum(w, 0.0)
    return _finalize("min_variance", names, w, returns, note="no-short clip applied")


def max_sharpe(returns: pd.DataFrame, risk_free: float = 0.0) -> PortfolioResult:
    names = list(returns.columns)
    S = _cov(returns)
    mu = _mean(returns) - risk_free
    n = len(names)
    ones = np.ones(n)
    try:
        inv = np.linalg.inv(S + np.eye(n) * 1e-10)
        denom = ones @ inv @ mu
        if abs(denom) < 1e-12:
            w = np.full(n, 1.0 / n)
        else:
            w = inv @ mu / denom
    except np.linalg.LinAlgError:  # pragma: no cover - defensive
        w = np.full(n, 1.0 / n)
    w = np.maximum(w, 0.0)
    return _finalize("max_sharpe", names, w, returns, note="no-short clip applied")


def risk_parity(returns: pd.DataFrame, max_iter: int = 200, tol: float = 1e-8) -> PortfolioResult:
    names = list(returns.columns)
    S = _cov(returns)
    n = len(names)
    w = np.full(n, 1.0 / n)
    converged = False
    for _ in range(max_iter):
        Sw = S @ w
        contrib = w * Sw
        avg = float(np.mean(contrib))
        if avg <= 0:
            break
        w_new = w * (avg / contrib)
        w_new = w_new / np.sum(w_new)
        if np.max(np.abs(w_new - w)) < tol:
            w = w_new
            converged = True
            break
        w = w_new
    had_neg = bool(np.any(w < 0))
    w = np.maximum(w, 0.0)
    note = None
    if not converged:
        note = "did not fully converge; iterative fixpoint applied"
    elif had_neg:
        note = "negative weights clipped (no-short)"
    return _finalize("risk_parity", names, w, returns, note=note)


def _finalize(
    method: str,
    names: list[str],
    w: np.ndarray,
    returns: pd.DataFrame,
    note: str | None = None,
) -> PortfolioResult:
    w = np.asarray(w, dtype=float)
    if w.sum() > 0:
        w = w / np.sum(w)
    weights = _safe_weights(w, names)
    clean = returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    p_ret = clean.mean().to_numpy() @ w
    p_var = float(w @ clean.cov().to_numpy() @ w)
    p_vol = np.sqrt(max(p_var, 0.0))
    ann_factor = 252
    ann_ret = _finite((1 + p_ret) ** ann_factor - 1)
    ann_vol = _finite(p_vol * np.sqrt(ann_factor))
    sharpe = _finite(ann_ret / ann_vol) if ann_vol > 0 else 0.0
    return PortfolioResult(
        method=method,
        weights=weights,
        expected_annual_return=ann_ret,
        expected_annual_vol=ann_vol,
        sharpe=sharpe,
        n_assets=len(names),
        notes=[note] if note else [],
    )


def optimize(returns: pd.DataFrame, method: str, risk_free: float = 0.05, **kwargs: Any) -> PortfolioResult:
    if method not in METHODS:
        raise ValueError(f"unknown optimizer '{method}' (choose from {METHODS})")
    if method == "equal_weight":
        return equal_weight(returns)
    if method == "inverse_vol":
        return inverse_vol(returns)
    if method == "min_variance":
        return min_variance(returns, risk_free)
    if method == "max_sharpe":
        return max_sharpe(returns, risk_free)
    if method == "risk_parity":
        return risk_parity(returns, **kwargs)
    raise ValueError(method)  # pragma: no cover


def list_methods() -> list[str]:
    return list(METHODS)
