"""Minimal, dependency-free cron engine for scheduled research.

Supports the standard 5-field cron expression ``minute hour dom month dow``
with ``*``, lists, ranges and ``*/step``. No external croniter dependency.
``next_occurrence`` computes the next matching naive datetime after a given
``datetime``; IANA timezone handling lives in the scheduler service. If the
expression can never match (e.g. ``0 0 30 2 *``), a clear error is raised.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

_MIN = 60 * 24 * 366 * 8  # search cap: 8 years minute-by-minute (correct, bounded)


class CronError(ValueError):
    pass


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"empty cron field segment in '{field}'")
        step = 1
        if "/" in part:
            part, _, step_s = part.partition("/")
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronError(f"bad step '{step_s}' in '{field}'")
            step = int(step_s)
        if part == "*":
            rng = (lo, hi)
        elif "-" in part:
            a, _, b = part.partition("-")
            if not a.isdigit() or not b.isdigit():
                raise CronError(f"bad range '{part}' in '{field}'")
            rng = (int(a), int(b))
        else:
            if not part.isdigit():
                raise CronError(f"bad token '{part}' in '{field}'")
            rng = (int(part), int(part))
        a, b = rng
        if not (lo <= a <= hi and lo <= b <= hi) or a > b:
            raise CronError(f"field out of range '{part}' in '{field}'")
        out.update(range(a, b + 1, step))
    return out


class CronSpec:
    """Parsed cron expression with per-field membership checks."""

    def __init__(self, expression: str):
        fields = expression.split()
        if len(fields) != 5:
            raise CronError(f"expected 5 cron fields, got {len(fields)} in '{expression}'")
        self.minutes = _parse_field(fields[0], 0, 59)
        self.hours = _parse_field(fields[1], 0, 23)
        self.doms = _parse_field(fields[2], 1, 31)
        self.months = _parse_field(fields[3], 1, 12)
        self.dows = {(d + 6) % 7 for d in _parse_field(fields[4], 0, 6)}  # cron Sun=0 -> py Mon=0
        self.dom_restricted = fields[2] != "*"
        self.dow_restricted = fields[4] != "*"
        self.expression = expression

    def day_matches(self, d: datetime) -> bool:
        dom_ok = d.day in self.doms
        dow_ok = d.weekday() in self.dows  # self.dows already mapped to Python weekday
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok  # standard cron: OR when both restricted
        if self.dom_restricted:
            return dom_ok
        if self.dow_restricted:
            return dow_ok
        return True

    def matches(self, d: datetime) -> bool:
        return (
            d.minute in self.minutes
            and d.hour in self.hours
            and d.month in self.months
            and self.day_matches(d)
        )


def parse_cron(expression: str) -> CronSpec:
    return CronSpec(expression)


def next_occurrence(spec: CronSpec, after: datetime) -> datetime:
    """Next datetime matching ``spec`` strictly after ``after`` (floored to
    the minute). Raises ``CronError`` if none exists within the search cap."""
    cur = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(_MIN):
        if spec.matches(cur):
            return cur
        cur += timedelta(minutes=1)
    raise CronError(f"cron '{spec.expression}' has no next occurrence within 8 years")


def next_occurrence_after(expression: str, after: datetime) -> datetime:
    """Convenience: parse + compute."""
    return next_occurrence(parse_cron(expression), after)
