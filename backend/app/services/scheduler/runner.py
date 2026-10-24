"""Deterministic playbook runner for scheduled research.

Playbooks run on real StockOS data with no LLM call and never fabricate
results — every output derives from live quotes/candles. Supported types:
``technical_summary``, ``backtest``, ``factor_ic`` and ``swarm`` (a preset DAG
executed node-by-node with real-data evidence per node)."""

from __future__ import annotations

import asyncio

from app.services.backtesting.engine_v2 import BacktestRequest, run_backtest
from app.services.data.ohlcv import sanitize_history, to_dataframe
from app.services.data.service import market_data
from app.services.factors.analysis import ic_analysis
from app.services.technical.indicators import TechnicalIndicators


def _stats(history: dict) -> dict:
    candles = (history or {}).get("candles") or []
    if len(candles) < 30:
        return {"error": "not enough candles", "n": len(candles)}
    df = to_dataframe(sanitize_history(history))
    close = df["close"].tolist()
    change = close[-1] / close[-30] - 1 if len(close) > 30 else 0.0
    rsi = TechnicalIndicators.rsi(close)
    sma20 = TechnicalIndicators.sma(close, 20)
    sma50 = TechnicalIndicators.sma(close, 50)
    returns = df["close"].pct_change().dropna()
    vol = float(returns.std(ddof=1) * (252 ** 0.5)) if len(returns) > 5 else 0.0
    dd = float((df["close"] / df["close"].cummax() - 1).min())
    return {
        "last_close": float(close[-1]),
        "change_30d_pct": round(change * 100, 3),
        "rsi": float(rsi),
        "sma20": float(sma20),
        "sma50": float(sma50),
        "sma_cross": "bullish" if sma20 > sma50 else "bearish",
        "vol_annualized": round(vol * 100, 2),
        "max_drawdown_30d": round(dd * 100, 2),
        "trend_score": round((close[-1] / sma20 - 1) * 100, 3),
    }


def _verdict(stats: list[dict]) -> dict:
    votes = [s["sma_cross"] for s in stats if s.get("sma_cross")]
    bullish = votes.count("bullish")
    total = len(votes) or 1
    if bullish / total >= 0.6:
        return {"rating": "BUY", "conviction": round(bullish / total, 2)}
    if bullish / total <= 0.4:
        return {"rating": "SELL", "conviction": round(1 - bullish / total, 2)}
    return {"rating": "HOLD", "conviction": round(abs(0.5 - bullish / total) + 0.5, 2)}


async def _fetch(symbols: list[str], period: str = "2y") -> dict:
    histories, failures = {}, []
    async def _one(symbol: str) -> None:
        try:
            histories[symbol] = await market_data.get_history_auto(symbol, interval="1d", period=period)
        except Exception:
            failures.append(symbol)
    await asyncio.gather(*(_one(s) for s in symbols))
    return {"histories": histories, "failures": failures}


async def _technical_summary(pb: dict, *, user_id: str | None = None) -> dict:
    symbols = pb.get("symbols") or []
    if not symbols:
        return {"error": "playbook needs 'symbols'"}
    data = await _fetch(symbols)
    stats = {s: _stats(h) for s, h in data["histories"].items()}
    return {
        "type": "technical_summary",
        "symbols": symbols,
        "failures": data["failures"],
        "stats": stats,
        "verdict": _verdict(list(stats.values())),
    }


async def _backtest(pb: dict, *, user_id: str | None = None) -> dict:
    symbol = pb.get("symbol") or pb.get("symbols", [None])[0]
    if not symbol:
        return {"error": "playbook needs a symbol"}
    history = await market_data.get_history_auto(symbol, interval=pb.get("interval", "1d"), period=pb.get("period", "3y"))
    df = to_dataframe(sanitize_history(history))
    if df.empty:
        return {"error": "no data", "symbol": symbol}
    result = run_backtest(
        df,
        BacktestRequest(
            symbol=symbol,
            interval=pb.get("interval", "1d"),
            period=pb.get("period", "3y"),
            strategy=pb.get("strategy", "moving_average_crossover"),
            params=pb.get("params", {}) or {},
            initial_capital=pb.get("initial_capital", 100000.0),
            validate=bool(pb.get("run_validation", False)),
        ),
    )
    return {"type": "backtest", "symbol": symbol, "result": result}


async def _factor_ic(pb: dict, *, user_id: str | None = None) -> dict:
    symbols = pb.get("symbols") or []
    factors = pb.get("factors") or ["alpha101_001"]
    if not symbols:
        return {"error": "playbook needs 'symbols'"}
    data = await _fetch(symbols)
    from app.services.factors.analysis import build_panel

    panel = build_panel(data["histories"], factors)
    if panel.empty:
        return {"error": "no panel data", "symbols": symbols}
    ic = ic_analysis(panel, factors, pb.get("forward_days", 1))
    return {"type": "factor_ic", "symbols": symbols, "failures": data["failures"], "ic": ic}


_NODE_HANDLERS: dict[str, callable] = {}


def _register(role: str):
    def deco(fn):
        _NODE_HANDLERS[role] = fn
        return fn
    return deco


async def _swarm(pb: dict, *, user_id: str | None = None) -> dict:
    from app.services.agents.swarm_presets import build_dag

    preset_id = pb.get("preset") or "quant-sweep"
    symbols = pb.get("symbols") or []
    if not symbols:
        return {"error": "swarm playbook needs 'symbols'"}
    dag = build_dag(preset_id, {"symbols": symbols})
    if "error" in dag:
        return dag
    data = await _fetch(symbols)
    ctx: dict = {"symbols": symbols, "histories": data["histories"], "failures": data["failures"]}
    outputs: dict[str, dict] = {}
    order = dag["nodes"]
    for node in order:
        role = node["role"]
        inputs = {d: outputs[d] for d in node["depends_on"] if d in outputs}
        handler = _NODE_HANDLERS.get(role) or _generic_node(role)
        try:
            outputs[role] = await handler(ctx, inputs)
        except Exception as exc:  # node must not kill the run
            outputs[role] = {"error": str(exc)}
    return {
        "type": "swarm",
        "preset": preset_id,
        "symbols": symbols,
        "failures": data["failures"],
        "nodes": outputs,
    }


def _generic_node(role: str):
    async def handler(ctx: dict, inputs: dict) -> dict:
        stats = {s: _stats(h) for s, h in ctx["histories"].items()}
        return {
            "role": role,
            "n_symbols": len(ctx["symbols"]),
            "stats": stats,
            "verdict": _verdict(list(stats.values())),
            "inputs": list(inputs.keys()),
        }
    return handler


@_register("data")
async def _data_node(ctx: dict, inputs: dict) -> dict:
    quotes = {}
    for s in ctx["symbols"]:
        h = ctx["histories"].get(s) or {}
        candles = h.get("candles") or []
        if candles:
            quotes[s] = {"last_close": candles[-1]["close"], "ts": candles[-1]["ts"]}
    return {"role": "data", "quotes": quotes, "failures": ctx["failures"]}


@_register("technical")
@_register("analyze")
async def _technical_node(ctx: dict, inputs: dict) -> dict:
    stats = {s: _stats(h) for s, h in ctx["histories"].items()}
    return {"role": "technical", "stats": stats, "verdict": _verdict(list(stats.values()))}


@_register("screen")
async def _screen_node(ctx: dict, inputs: dict) -> dict:
    from app.services.factors.blend import composite_signal
    from app.services.factors.analysis import build_panel

    factor = "alpha101_001"
    panel = build_panel(ctx["histories"], [factor])
    if panel.empty:
        return {"role": "screen", "error": "no panel"}
    sig = composite_signal(panel, {factor: 1.0})
    last = sig.groupby(level=0).last().sort_values(ascending=False)
    top = [s for s in last.index[: max(1, len(last) // 2)]]
    return {"role": "screen", "factor": factor, "top_symbols": top}


@_register("verify")
async def _verify_node(ctx: dict, inputs: dict) -> dict:
    from app.services.agents.grounding import grounding_gate

    check = ""
    for node_in, out in inputs.items():
        text = str(out.get("verdict", "")) + " " + str(out.get("stats", ""))
        check += f"{node_in}: {text} "
    facts = []
    for s in ctx["symbols"]:
        h = ctx["histories"].get(s) or {}
        candles = h.get("candles") or []
        if candles:
            facts.append({"label": "close", "value": candles[-1]["close"], "symbol": s})
    return {"role": "verify", "gate": grounding_gate.verify(check, facts)}


@_register("decide")
async def _decide_node(ctx: dict, inputs: dict) -> dict:
    verdicts = [v["verdict"] for v in inputs.values() if isinstance(v.get("verdict"), dict)]
    if verdicts:
        ratings = [v["rating"] for v in verdicts]
        from collections import Counter

        counter = Counter(ratings)
        winner = counter.most_common(1)[0][0]
        return {"role": "decide", "verdict": {"rating": winner, "votes": dict(counter)}}
    stats = {s: _stats(h) for s, h in ctx["histories"].items()}
    return {"role": "decide", "verdict": _verdict(list(stats.values()))}


async def run_playbook(playbook: dict, user_id: str | None = None) -> dict:
    ptype = (playbook or {}).get("type", "technical_summary")
    handlers = {
        "technical_summary": _technical_summary,
        "backtest": _backtest,
        "factor_ic": _factor_ic,
        "swarm": _swarm,
        "autopilot": _autopilot,
    }
    handler = handlers.get(ptype)
    if handler is None:
        return {"error": f"unknown playbook type '{ptype}'"}
    try:
        return await handler(playbook, user_id=user_id)
    except Exception as exc:
        return {"error": f"playbook failed: {exc}"}


async def _autopilot(pb: dict, *, user_id: str | None = None) -> dict:
    """Run the agent autopilot as a scheduled playbook (real, per-user).

    Requires a user id so the mission runs against that user's broker/
    config/memory. Tunables inside the playbook are patched over the user's
    saved autopilot config.
    """
    if not user_id:
        return {"error": "autopilot playbook needs a user_id (run it as a scheduled autopilot)"}
    from app.services.autopilot.engine import autopilot_engine

    patch = {k: v for k, v in (pb or {}).items() if k not in ("type", "symbols", "symbol", "user_id")}
    if patch:
        await autopilot_engine.save_config(user_id, patch)
    monitor_only = bool((pb or {}).get("monitor_only", False))
    run = await autopilot_engine.run(user_id, monitor_only=monitor_only)
    return {"type": "autopilot", "mission": run["mission"], "status": run["status"], "summary": run.get("summary"), "report": run.get("report"), "node_phases": [n["phase"] for n in (run.get("nodes") or [])]}
