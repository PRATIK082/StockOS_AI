"""Factor registry: metadata + dispatch for every computable factor.

Currently ships the full alpha101 set (see ``alpha101.py``). GTJA-191 and
Qlib-158 factor families plug into the exact same seam (``FACTOR_SOURCES`` +
``compute_factor``), so the "462-factor zoo" can grow without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.services.factors.alpha101 import ALPHAS, ALPHA_DESCRIPTIONS, compute as compute_alpha101


@dataclass
class FactorSpec:
    name: str
    family: str
    category: str
    description: str


FACTOR_SOURCES: dict[str, dict[str, object]] = {
    "alpha101": ALPHAS,
}

CATEGORY = {
    "alpha101": "momentum / volume / reversal (WorldQuant-style formulaic)",
}


def _all_specs() -> list[FactorSpec]:
    specs: list[FactorSpec] = []
    for family, fns in FACTOR_SOURCES.items():
        for name in sorted(fns):
            specs.append(
                FactorSpec(
                    name=name,
                    family=family,
                    category=CATEGORY.get(family, family),
                    description=ALPHA_DESCRIPTIONS.get(name, ""),
                )
            )
    return specs


def list_factors() -> list[dict]:
    return [
        {
            "name": s.name,
            "family": s.family,
            "category": s.category,
            "description": s.description,
        }
        for s in _all_specs()
    ]


def count_factors() -> int:
    return len(_all_specs())


def compute_factor(df: pd.DataFrame, name: str) -> pd.Series:
    """Compute a single factor by name over an OHLCV frame (NaN warm-up bars)."""
    if name in ALPHAS:
        return compute_alpha101(df, [name])[name]
    raise KeyError(f"unknown factor '{name}'")
