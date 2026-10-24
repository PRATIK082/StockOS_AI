"""GroundingGate: deterministic, LLM-free verification of agent output against
real evidence. Every sentence of a report is classified as *supported* (its
numeric claims match the evidence), *unverifiable* (no checkable numbers /
context), or *contradicted* (a labeled numeric claim disagrees with the facts).
No fabricated verification: a report without matching evidence simply scores
lower, it is never "proven" by fiat."""

from __future__ import annotations

import re

_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_QUANT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(%|billion|million|cr|k|₹|rs\.?|\$)?", re.IGNORECASE)


def _to_number(token: str) -> float | None:
    t = token.replace(",", "").replace("₹", "").replace("$", "").replace("%", "")
    try:
        return float(t)
    except ValueError:
        return None


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _close(a: float, b: float, tol: float = 0.02) -> bool:
    if b == 0:
        return abs(a) < 0.5
    return abs(a - b) / abs(b) <= tol or abs(a - b) <= 0.5


class GroundingResult:
    def __init__(self, sentences: list[dict], facts: list[dict]):
        self.sentences = sentences
        self.facts = facts
        self.verdicts = [s["verdict"] for s in sentences]
        n = len(self.verdicts)
        self.supported = self.verdicts.count("supported")
        self.unverifiable = self.verdicts.count("unverifiable")
        self.contradicted = self.verdicts.count("contradicted")
        total = n or 1
        self.supported_pct = round(self.supported / total, 4)
        self.passed = self.contradicted == 0 and self.supported_pct >= 0.5
        self.contradictions = [s["text"] for s in sentences if s["verdict"] == "contradicted"]

    def to_dict(self) -> dict:
        return {
            "supported": self.supported,
            "unverifiable": self.unverifiable,
            "contradicted": self.contradicted,
            "supported_pct": self.supported_pct,
            "passed": self.passed,
            "contradictions": self.contradictions,
            "sentences": self.sentences,
        }


class GroundingGate:
    """Verify a report's numeric claims against real evidence facts."""

    def verify(self, text: str, facts: list[dict]) -> dict:
        """``facts``: list of ``{"label": str, "value": float, "symbol": str|None}``
        e.g. ``{"label": "close", "value": 2473.4, "symbol": "NSE:RELIANCE"}``."""
        if not text:
            return {"passed": False, "supported": 0, "unverifiable": 0, "contradicted": 0,
                    "supported_pct": 0.0, "contradictions": [], "sentences": [], "reason": "empty report"}
        facts = [f for f in facts if isinstance(f.get("value"), (int, float))]
        labels = {str(f.get("label", "")).lower(): float(f["value"]) for f in facts if f.get("label")}
        symbols = {str(f.get("symbol", "")).upper(): None for f in facts if f.get("symbol")}

        results = []
        for sentence in _sentences(text):
            low = sentence.lower()
            tokens = _NUMBER_RE.findall(sentence)
            numbers = [n for n in (_to_number(t) for t in tokens) if n is not None]
            mentioned_symbol = next((s for s in symbols if s in low), None)
            mentioned_label = next((lbl for lbl in labels if lbl in low), None)
            if not numbers:
                verdict = "unverifiable"
                evidence = None
            elif mentioned_label and mentioned_label in labels:
                target = labels[mentioned_label]
                if any(_close(n, target) for n in numbers):
                    verdict, evidence = "supported", {"label": mentioned_label, "value": target}
                else:
                    verdict, evidence = "contradicted", {
                        "label": mentioned_label,
                        "expected": target,
                        "found": [n for n in numbers],
                    }
            elif mentioned_symbol and numbers:
                verdict, evidence = "unverifiable", {"symbol": mentioned_symbol}
            else:
                evidence = None
                verdict = "supported" if any(
                    _close(n, f["value"]) for f in facts for n in numbers
                ) else "unverifiable"
            results.append(
                {"text": sentence, "verdict": verdict, "evidence": evidence}
            )
        return GroundingResult(results, facts).to_dict()


grounding_gate = GroundingGate()
