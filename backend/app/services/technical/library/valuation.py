"""Valuation helpers ported from cinar/indicator.

Port of the ``valuation`` package of https://github.com/cinar/indicator
(Cinar Indicator Project, Onur Cinar), licensed under GNU AGPLv3,
Copyright (c) 2021-2026 Onur Cinar.

These are scalar helpers (not series indicators).  Argument order and sign
conventions match the Go signatures exactly: ``rate`` is a decimal fraction
(0.1 == 10%), a single lump-sum present/future value, and NPV discounts each
cash flow by ``(1+rate)^i`` for i = 1..n (positive inflows).
"""

from __future__ import annotations

from collections.abc import Iterable
from numbers import Real


def fv(pv, rate, years):
    """Future value of a present value: ``PV * (1+rate)^years``.  Returns float."""
    pv = float(pv)
    return pv * (1.0 + float(rate)) ** int(years)


def pv(fv, rate, years):
    """Present value of a future value: ``FV / (1+rate)^years``.  Returns float."""
    fv = float(fv)
    return fv / (1.0 + float(rate)) ** int(years)


def npv(rate, cash_flows):
    """Net present value ``sum(CF_i / (1+rate)^i)``, i = 1..n.  Returns float."""
    df = 1.0 + float(rate)
    total = 0.0
    for i, cf in enumerate(cash_flows):
        if not isinstance(cf, Real):
            raise TypeError(f"cash flow at index {i} must be a real number")
        total += float(cf) / df ** (i + 1)
    return total