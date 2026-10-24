"""Swarm DAG presets: 30 named multi-agent workflow templates.

Each preset is pure data — ``nodes`` (agent roles) + ``edges`` (dependencies)
forming a DAG that the swarm executor (Phase 6+) can run as a graph of LLM
agent calls over real StockOS data. ``id`` values are stable slugs; adding a
preset never touches existing code."""

from __future__ import annotations

PRESETS: list[dict] = [
    {
        "id": "quant-sweep",
        "name": "Quant sweep",
        "description": "Screen the universe on a factor, verify the signal, then decide.",
        "nodes": ["screen", "verify", "analyze", "decide"],
        "edges": [["screen", "verify"], ["verify", "analyze"], ["analyze", "decide"]],
    },
    {
        "id": "deep-research",
        "name": "Deep research",
        "description": "Parallel data/research agents feed a synthesizer and a reviewer.",
        "nodes": ["data", "sentiment", "news", "fundamentals", "synthesize", "review"],
        "edges": [
            ["data", "synthesize"], ["sentiment", "synthesize"], ["news", "synthesize"],
            ["fundamentals", "synthesize"], ["synthesize", "review"],
        ],
    },
    {
        "id": "bull-bear-court",
        "name": "Bull/bear court",
        "description": "Adversarial bull and bear cases, cross-examined, then a verdict.",
        "nodes": ["data", "bull", "bear", "cross_examine", "verdict"],
        "edges": [
            ["data", "bull"], ["data", "bear"],
            ["bull", "cross_examine"], ["bear", "cross_examine"],
            ["cross_examine", "verdict"],
        ],
    },
    {
        "id": "options-view",
        "name": "Options view",
        "description": "Chain snapshot → IV/max-pain analysis → options verdict.",
        "nodes": ["data", "options_chain", "iv_skew", "max_pain", "options_verdict"],
        "edges": [
            ["data", "options_chain"], ["options_chain", "iv_skew"],
            ["options_chain", "max_pain"], ["iv_skew", "options_verdict"],
            ["max_pain", "options_verdict"],
        ],
    },
    {
        "id": "risk-first",
        "name": "Risk first",
        "description": "Risk x-ray gates the trade: only a passing risk gate reaches decision.",
        "nodes": ["data", "risk_xray", "strategy", "decision"],
        "edges": [["data", "risk_xray"], ["data", "strategy"], ["risk_xray", "decision"], ["strategy", "decision"]],
    },
    {
        "id": "signal-stack",
        "name": "Signal stack",
        "description": "Technical, sentiment and news signals each vote before a consensus.",
        "nodes": ["data", "technical", "sentiment", "news", "consensus"],
        "edges": [
            ["data", "technical"], ["data", "sentiment"], ["data", "news"],
            ["technical", "consensus"], ["sentiment", "consensus"], ["news", "consensus"],
        ],
    },
    {
        "id": "watchlist-review",
        "name": "Watchlist review",
        "description": "Rank each watchlist name, merge into one summary memo.",
        "nodes": ["watchlist", "rank", "memo"],
        "edges": [["watchlist", "rank"], ["rank", "memo"]],
    },
    {
        "id": "sector-rotate",
        "name": "Sector rotation",
        "description": "Score sectors on momentum, then pick the leaders within the top sector.",
        "nodes": ["data", "sector_momentum", "sector_rank", "leader_pick"],
        "edges": [["data", "sector_momentum"], ["sector_momentum", "sector_rank"], ["sector_rank", "leader_pick"]],
    },
    {
        "id": "backtest-loop",
        "name": "Backtest loop",
        "description": "Parameterize, backtest, validate, then critique the results.",
        "nodes": ["param", "backtest", "validate", "critique"],
        "edges": [["param", "backtest"], ["backtest", "validate"], ["validate", "critique"]],
    },
    {
        "id": "factor-drilldown",
        "name": "Factor drilldown",
        "description": "IC analysis → factor bench → attribution of the winning factor.",
        "nodes": ["data", "ic", "bench", "attribution"],
        "edges": [["data", "ic"], ["ic", "bench"], ["bench", "attribution"]],
    },
    {
        "id": "earnings-read",
        "name": "Earnings read",
        "description": "Fundamentals vs. consensus, price reaction, then a rating.",
        "nodes": ["fundamentals", "consensus_compare", "price_reaction", "rating"],
        "edges": [
            ["fundamentals", "consensus_compare"], ["consensus_compare", "rating"],
            ["price_reaction", "rating"],
        ],
    },
    {
        "id": "defensive-check",
        "name": "Defensive check",
        "description": "Drawdown, tail-risk and liquidity guards feed a go/no-go.",
        "nodes": ["data", "drawdown", "tail_risk", "liquidity", "go_no_go"],
        "edges": [
            ["data", "drawdown"], ["data", "tail_risk"], ["data", "liquidity"],
            ["drawdown", "go_no_go"], ["tail_risk", "go_no_go"], ["liquidity", "go_no_go"],
        ],
    },
    {
        "id": "news-sentiment-pulse",
        "name": "News sentiment pulse",
        "description": "Fresh news → sentiment score → a one-line pulse summary.",
        "nodes": ["news", "sentiment", "pulse"],
        "edges": [["news", "sentiment"], ["sentiment", "pulse"]],
    },
    {
        "id": "portfolio-xray",
        "name": "Portfolio x-ray",
        "description": "Exposure, risk and attribution agents produce a portfolio memo.",
        "nodes": ["data", "exposure", "risk", "attribution", "memo"],
        "edges": [
            ["data", "exposure"], ["data", "risk"], ["data", "attribution"],
            ["exposure", "memo"], ["risk", "memo"], ["attribution", "memo"],
        ],
    },
    {
        "id": "crypto-watch",
        "name": "Crypto watch",
        "description": "Crypto quotes/vol → trend → trade-worthy note.",
        "nodes": ["data", "volatility", "trend", "note"],
        "edges": [["data", "volatility"], ["data", "trend"], ["volatility", "note"], ["trend", "note"]],
    },
    {
        "id": "fundamental-verify",
        "name": "Fundamental verify",
        "description": "Verify fundamentals, flag gaps, then score quality.",
        "nodes": ["fundamentals", "verify", "quality_score"],
        "edges": [["fundamentals", "verify"], ["verify", "quality_score"]],
    },
    {
        "id": "trend-following",
        "name": "Trend following",
        "description": "MA cross + momentum + volume confirm a trend trade.",
        "nodes": ["data", "ma_cross", "momentum", "volume", "trend_trade"],
        "edges": [
            ["data", "ma_cross"], ["data", "momentum"], ["data", "volume"],
            ["ma_cross", "trend_trade"], ["momentum", "trend_trade"], ["volume", "trend_trade"],
        ],
    },
    {
        "id": "mean-reversion",
        "name": "Mean reversion",
        "description": "RSI + Bollinger extremes + volume spike → reversion setup.",
        "nodes": ["data", "rsi", "bollinger", "volume", "setup"],
        "edges": [
            ["data", "rsi"], ["data", "bollinger"], ["data", "volume"],
            ["rsi", "setup"], ["bollinger", "setup"], ["volume", "setup"],
        ],
    },
    {
        "id": "gap-analysis",
        "name": "Gap analysis",
        "description": "Open-gap vs. fair value → gap-fill probability note.",
        "nodes": ["data", "gap_detect", "fair_value", "gap_note"],
        "edges": [["data", "gap_detect"], ["data", "fair_value"], ["gap_detect", "gap_note"], ["fair_value", "gap_note"]],
    },
    {
        "id": "ipo-take",
        "name": "IPO take",
        "description": "Subscription, GMP and peer comps → IPO verdict.",
        "nodes": ["data", "subscription", "gmp", "comps", "verdict"],
        "edges": [
            ["data", "subscription"], ["data", "gmp"], ["data", "comps"],
            ["subscription", "verdict"], ["gmp", "verdict"], ["comps", "verdict"],
        ],
    },
    {
        "id": "index-health",
        "name": "Index health",
        "description": "Index breadth, volatility and trend give a regime call.",
        "nodes": ["data", "breadth", "volatility", "trend", "regime"],
        "edges": [
            ["data", "breadth"], ["data", "volatility"], ["data", "trend"],
            ["breadth", "regime"], ["volatility", "regime"], ["trend", "regime"],
        ],
    },
    {
        "id": "ticker-tale",
        "name": "Ticker tale",
        "description": "One-symbol narrative: data → story → risk caveat → summary.",
        "nodes": ["data", "story", "risk", "summary"],
        "edges": [["data", "story"], ["data", "risk"], ["story", "summary"], ["risk", "summary"]],
    },
    {
        "id": "multi-timeframe",
        "name": "Multi-timeframe",
        "description": "Daily, weekly and monthly views converge into a trade plan.",
        "nodes": ["daily", "weekly", "monthly", "plan"],
        "edges": [["daily", "plan"], ["weekly", "plan"], ["monthly", "plan"]],
    },
    {
        "id": "stop-loss-eng",
        "name": "Stop-loss engineering",
        "description": "ATR-based stop, mental stop, then a position-size plan.",
        "nodes": ["data", "atr_stop", "mental_stop", "size"],
        "edges": [["data", "atr_stop"], ["atr_stop", "mental_stop"], ["mental_stop", "size"]],
    },
    {
        "id": "credit-check",
        "name": "Credit check",
        "description": "Liquidity, leverage and default-risk agents triage credit.",
        "nodes": ["data", "liquidity", "leverage", "default_risk", "triage"],
        "edges": [
            ["data", "liquidity"], ["data", "leverage"], ["data", "default_risk"],
            ["liquidity", "triage"], ["leverage", "triage"], ["default_risk", "triage"],
        ],
    },
    {
        "id": "vol-surface",
        "name": "Vol surface",
        "description": "Build the surface, note skew/term, then a vol trade idea.",
        "nodes": ["data", "surface", "skew_term", "trade_idea"],
        "edges": [["data", "surface"], ["surface", "skew_term"], ["skew_term", "trade_idea"]],
    },
    {
        "id": "momentum-hunt",
        "name": "Momentum hunt",
        "description": "Rank momentum leaders, verify volume, shortlist.",
        "nodes": ["data", "momentum_rank", "volume_verify", "shortlist"],
        "edges": [["data", "momentum_rank"], ["momentum_rank", "volume_verify"], ["volume_verify", "shortlist"]],
    },
    {
        "id": "earnings-call-note",
        "name": "Earnings call note",
        "description": "Extract guidance, compare guidance vs. price, write the note.",
        "nodes": ["transcript", "guidance", "compare", "note"],
        "edges": [["transcript", "guidance"], ["guidance", "compare"], ["compare", "note"]],
    },
    {
        "id": "pre-market-brief",
        "name": "Pre-market brief",
        "description": "Overnight, gaps and watchlist names → a morning brief.",
        "nodes": ["overnight", "gaps", "watchlist", "brief"],
        "edges": [["overnight", "brief"], ["gaps", "brief"], ["watchlist", "brief"]],
    },
    {
        "id": "weekly-review",
        "name": "Weekly review",
        "description": "Week stats, winners/losers, then next-week plan.",
        "nodes": ["stats", "winners", "losers", "next_week"],
        "edges": [
            ["stats", "winners"], ["stats", "losers"], ["stats", "next_week"],
            ["winners", "next_week"], ["losers", "next_week"],
        ],
    },
]

_BY_ID: dict[str, dict] = {p["id"]: p for p in PRESETS}


def list_presets() -> list[dict]:
    return [
        {"id": p["id"], "name": p["name"], "description": p["description"],
         "n_nodes": len(p["nodes"]), "n_edges": len(p["edges"])}
        for p in PRESETS
    ]


def get_preset(preset_id: str) -> dict | None:
    return _BY_ID.get(preset_id)


def build_dag(preset_id: str, params: dict | None = None) -> dict:
    """Return the preset as an executable DAG description: nodes with their
    declared dependencies and the requested parameter bindings."""
    preset = get_preset(preset_id)
    if preset is None:
        return {"error": f"unknown preset '{preset_id}'"}
    deps: dict[str, list[str]] = {n: [] for n in preset["nodes"]}
    for src, dst in preset["edges"]:
        deps.setdefault(dst, []).append(src)
    return {
        "id": preset_id,
        "name": preset["name"],
        "description": preset["description"],
        "params": params or {},
        "nodes": [{"role": n, "depends_on": sorted(deps[n])} for n in preset["nodes"]],
    }
