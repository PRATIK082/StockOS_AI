"""Factor signal blending: normalize raw factor values into comparable
cross-sectional signals and combine them into a weighted composite.

Normalization happens per-date across the symbol cross-section (no lookahead —
each date's signal uses only that date's factor values), so a momentum factor
measured in returns and a volatility factor measured in dollars become
additive. ``method="rank"`` maps values to [0,1] percentiles; ``"zscore"``
standardizes per date. Negative weights flip a factor's direction (e.g. a
``-1`` weight on a mean-reversion factor turns it into a trend signal).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.factors.registry import compute_factor


def zscore_cross_sectional(s: pd.Series) -> pd.Series:
    """Per-date z-score across the symbol cross-section (finite-safe)."""
    return s.groupby(level=1).transform(
        lambda x: (x - x.mean()) / x.std(ddof=0) if x.std(ddof=0) else 0.0
    )


def rank_cross_sectional(s: pd.Series) -> pd.Series:
    """Per-date percentile rank across the symbol cross-section (0..1)."""
    return s.groupby(level=1).rank(pct=True)


def normalize(s: pd.Series, method: str = "rank") -> pd.Series:
    if method == "rank":
        return rank_cross_sectional(s)
    if method == "zscore":
        return zscore_cross_sectional(s)
    raise ValueError(f"unknown normalization '{method}' (choose 'rank' or 'zscore')")


def composite_signal(
    panel: pd.DataFrame,
    weights: dict[str, float],
    method: str = "rank",
) -> pd.Series:
    """Weighted sum of normalized factors, re-indexed to the panel.

    ``weights`` maps factor name → signed weight. Unknown factor names are
    ignored (the caller should validate with the registry first).
    """
    if not weights:
        raise ValueError("composite_signal needs at least one factor weight")
    parts = []
    for name, weight in weights.items():
        if name not in panel.columns or not weight:
            continue
        parts.append(weight * normalize(panel[name], method))
    if not parts:
        raise ValueError("none of the requested factors are in the panel")
    out = parts[0]
    for p in parts[1:]:
        out = out.add(p, fill_value=0.0)
    return out


def build_signal_panel(
    histories: dict[str, dict],
    weights: dict[str, float],
    method: str = "rank",
) -> tuple[pd.DataFrame, pd.Series]:
    """One-shot: build a factor panel from histories and return (panel, signal)."""
    from app.services.factors.analysis import build_panel

    panel = build_panel(histories, list(weights))
    return panel, composite_signal(panel, weights, method)
