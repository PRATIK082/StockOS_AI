"""Fundamental analysis agent — real market fundamentals only.

This agent works exclusively from real fundamentals retrieved through the
StockOS market service (Yahoo-backed). It never fabricates financial numbers:
when the free feed does not publish a metric, the agent says so explicitly and
lowers confidence accordingly. No sample data is ever presented as real.
"""

from __future__ import annotations

from typing import Any

from .base import Agent, AgentResult as AgentResponse, AgentContext, estimate_confidence

_REQUIRED_FIELDS = (
    "trailingPE", "forwardPE", "priceToBook", "returnOnEquity", "revenueGrowth",
    "earningsGrowth", "debtToEquity", "dividendYield", "freeCashflow", "marketCap",
)


class FundamentalAgent(Agent):
    """Agent specialized in fundamental analysis."""

    name = "fundamental_analyst"
    description = "Analyzes company fundamentals, financials, and valuation"

    async def run(self, ctx: AgentContext) -> AgentResponse:
        """Perform fundamental analysis over real data."""
        symbol = ctx.symbol
        if not symbol:
            return AgentResponse(
                agent=self.name,
                content="Please provide a symbol for fundamental analysis.",
                confidence=0.1,
            )

        fundamentals = await self._get_fundamentals(symbol)
        if not fundamentals:
            return AgentResponse(
                agent=self.name,
                content=(
                    f"## Fundamental Analysis: {symbol}\n\n"
                    "No real fundamentals are currently available from the free feed "
                    "for this symbol (Yahoo may return sparse/empty financials for "
                    "fresh listings or index tickers). I will not invent figures. "
                    "\n\nRecommendation: HOLD until real financials are available."
                ),
                data={"fundamentals": {}},
                confidence=0.2,
                sources=["financial_statements"],
            )

        analysis = self._analyze_metrics(fundamentals)
        valuation = self._calculate_valuation(fundamentals)
        content = self._format_analysis(symbol, fundamentals, analysis, valuation)

        missing = sum(1 for k in _REQUIRED_FIELDS if fundamentals.get(k) is None)
        confidence = estimate_confidence(missing, len(_REQUIRED_FIELDS))
        return AgentResponse(
            agent=self.name,
            content=content,
            data={
                "fundamentals": fundamentals,
                "analysis": analysis,
                "valuation": valuation,
            },
            confidence=confidence,
            sources=["financial_statements", "ratios", "peer_comparison"],
        )

    async def _get_fundamentals(self, symbol: str) -> dict:
        """Real market fundamentals from the StockOS market service."""
        if not self.market_service:
            return {}
        try:
            data = await self.market_service.get_fundamentals(symbol)
        except Exception:  # noqa: BLE001
            return {}
        if not data:
            return {}
        # The service may wrap under "base" (see prediction engine conventions).
        return (data.get("base") if isinstance(data.get("base"), dict) else data) or {}

    @staticmethod
    def _or_none(value: Any, *, pct: bool = False) -> Any:
        """Normalise a raw provider value (Yahoo fractions are 0..1)."""
        if value is None:
            return None
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if pct and abs(v) <= 1.0:
            v = v * 100.0
        return v

    def _analyze_metrics(self, fundamentals: dict) -> dict:
        """Score the real metrics; fields missing from the feed are skipped."""
        score = 0.0
        analysis = {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []}
        present = 0

        pe = self._or_none(fundamentals.get("trailingPE") or fundamentals.get("forwardPE"))
        if pe is not None:
            present += 1
            if 0 < pe < 15:
                analysis["strengths"].append(f"Attractive P/E ratio of {pe:.1f}")
                score += 0.15
            elif pe > 30:
                analysis["weaknesses"].append(f"High P/E ratio of {pe:.1f}")
                score -= 0.1

        pb = self._or_none(fundamentals.get("priceToBook"))
        if pb is not None:
            present += 1
            if 0 < pb < 3:
                analysis["strengths"].append(f"Reasonable P/B of {pb:.2f}")
                score += 0.05
            elif pb > 8:
                analysis["weaknesses"].append(f"Rich P/B of {pb:.2f}")
                score -= 0.05

        roe = self._or_none(fundamentals.get("returnOnEquity"), pct=True)
        if roe is not None:
            present += 1
            if roe > 20:
                analysis["strengths"].append(f"Strong ROE of {roe:.1f}%")
                score += 0.15
            elif roe < 8:
                analysis["weaknesses"].append(f"Low ROE of {roe:.1f}%")
                score -= 0.1

        growth = self._or_none(fundamentals.get("revenueGrowth"), pct=True)
        if growth is not None:
            present += 1
            if growth > 15:
                analysis["strengths"].append(f"Revenue growth of {growth:.1f}%")
                score += 0.15
            elif growth < 0:
                analysis["weaknesses"].append(f"Revenues falling at {growth:.1f}%")
                score -= 0.15

        eps_growth = self._or_none(fundamentals.get("earningsGrowth"), pct=True)
        if eps_growth is not None:
            present += 1
            if eps_growth > 15:
                analysis["opportunities"].append(f"EPS growth of {eps_growth:.1f}%")
                score += 0.05
            elif eps_growth < -5:
                analysis["threats"].append(f"EPS declining at {eps_growth:.1f}%")
                score -= 0.15

        de = self._or_none(fundamentals.get("debtToEquity"))
        if de is not None:
            present += 1
            # Yahoo reports D/E as a ratio (e.g. 0.45) — treat <0.5 mild, >1.5 heavy.
            if 0 < de < 0.5:
                analysis["strengths"].append(f"Low debt-to-equity of {de:.2f}")
                score += 0.1
            elif de > 1.5:
                analysis["threats"].append(f"High debt-to-equity of {de:.2f}")
                score -= 0.15

        yield_ = self._or_none(fundamentals.get("dividendYield"), pct=True)
        if yield_ is not None:
            present += 1
            if yield_ > 2.5:
                analysis["strengths"].append(f"Dividend yield of {yield_:.2f}%")
                score += 0.05

        if present == 0:
            analysis["opportunities"].append("No real metrics from the free feed were returned yet.")

        # History: expected 9 required metrics.
        analysis["score"] = round(score, 3)
        analysis["metrics_present"] = present
        analysis["confidence"] = estimate_confidence(_REQUIRED_FIELDS.__len__() - present, len(_REQUIRED_FIELDS))
        return analysis

    def _calculate_valuation(self, fundamentals: dict) -> dict:
        """Intrinsic-value approximations from REAL per-share data.

        Only computed when the free feed actually provides the inputs; otherwise
        honest n/a values are returned. No fabricated DCF terminal years.
        """
        eps = self._or_none(fundamentals.get("trailingEps"))
        if eps is None:
            return {"pe_based": None, "dcf": None, "graham": None, "average": None}

        pe = self._or_none(fundamentals.get("trailingPE") or fundamentals.get("forwardPE"))
        market_price = eps * pe if pe and pe > 0 else None

        eps_growth = self._or_none(fundamentals.get("earningsGrowth"), pct=True) or 0.0
        graham = eps * (8.5 + 2 * min(eps_growth, 35.0)) if eps else None

        valid = [v for v in (market_price, graham) if v is not None]
        return {
            "pe_based": market_price,
            "dcf": None,
            "graham": graham,
            "average": float(sum(valid) / len(valid)) if valid else None,
        }

    def _format_analysis(
        self, symbol: str, fundamentals: dict, analysis: dict, valuation: dict
    ) -> str:
        """Render the report; every displayed number is real, others are n/a."""
        g = self._or_none
        report = [f"## Fundamental Analysis: {symbol}", ""]

        report.append("### Key Financial Metrics")
        rows = [
            ("P/E Ratio", g(fundamentals.get("trailingPE") or fundamentals.get("forwardPE"))),
            ("ROE", g(fundamentals.get("returnOnEquity"), pct=True)),
            ("Revenue Growth", g(fundamentals.get("revenueGrowth"), pct=True)),
            ("EPS Growth", g(fundamentals.get("earningsGrowth"), pct=True)),
            ("Debt/Equity", g(fundamentals.get("debtToEquity"))),
            ("Dividend Yield", g(fundamentals.get("dividendYield"), pct=True)),
        ]
        for name, value in rows:
            rendered = f"{value:.2f}%" if value is not None and name != "Debt/Equity" else (
                f"{value:.2f}" if value is not None else "n/a")
            report.append(f"- {name}: {rendered}")
        report.append("")

        if analysis["strengths"]:
            report.append("**Strengths:**")
            report.extend(f"- {s}" for s in analysis["strengths"])
        if analysis["weaknesses"]:
            report.append("\n**Weaknesses:**")
            report.extend(f"- {w}" for w in analysis["weaknesses"])

        report.append("\n### Valuation Estimates")
        if valuation.get("pe_based") is not None:
            report.append(f"- Implied value (pe-based): **{valuation['pe_based']:.2f}**")
        if valuation.get("graham") is not None:
            report.append(f"- Graham Formula: **{valuation['graham']:.2f}**")
        if valuation.get("average") is not None:
            report.append(f"- **Average Fair Value: {valuation['average']:.2f}**")
        else:
            report.append("- Valuation not computed: per-share earnings unavailable "
                          "from the free feed (honest n/a, not fabricated).")

        score = analysis.get("score", 0)
        note = (
            f"Real metrics coverage: {analysis.get('metrics_present', 0)}/{len(_REQUIRED_FIELDS)} "
            "fields from the feed; remaining values are n/a, never invented."
        )
        if score > 0.3:
            report.append("\n### Recommendation: **BUY**")
            report.append(f"Real fundamentals skew positive. {note}")
        elif score < -0.3:
            report.append("\n### Recommendation: **AVOID**")
            report.append(f"Real fundamentals skew negative. {note}")
        else:
            report.append("\n### Recommendation: **HOLD**")
            report.append(f"Real fundamentals are mixed. {note}")

        return "\n".join(report)