"""MCP tool registry: 62 async tools exposing StockOS engines to any MCP host
(Claude Desktop, Cursor, etc.) over a stdio JSON-RPC transport. Every tool is
backed by real engines — nothing is stubbed."""

from __future__ import annotations

from typing import Any

from app.services.backtesting.engine_v2 import run_backtest
from app.services.backtesting.strategies import list_strategies
from app.services.backtesting.costs import india_cost_config
from app.services.backtesting.validation import bootstrap_metrics, monte_carlo, walk_forward
from app.services.backtesting.risk_xray import risk_xray
from app.services.backtesting.portfolio_engine import optimize
from app.services.factors.registry import compute_factor, count_factors, list_factors
from app.services.factors.blend import composite_signal
from app.services.factors.backtest import factor_portfolio_backtest
from app.services.factors.analysis import build_panel, factor_bench, ic_analysis, quantile_returns
from app.services.quantlib.risk import cornish_fisher_var, evt_var, ewma_vol, parametric_var
from app.services.quantlib.portfolio import black_litterman, brinson_attribution
from app.services.quantlib.cashflow import irr, npv, xirr
from app.services.quantlib.options import greeks as greeks_fn
from app.services.quantlib.options import implied_volatility as iv_fn
from app.services.agents.grounding import grounding_gate
from app.services.agents.swarm_presets import build_dag, list_presets
from app.services.data.ohlcv import sanitize_history, to_dataframe
from app.services.data.service import market_data
from app.services.technical.indicators import TechnicalIndicators


async def _quote(args: dict) -> dict:
    return await market_data.get_quote(args["symbol"], args.get("provider"))


async def _history(args: dict) -> dict:
    h = await market_data.get_history_auto(args["symbol"], interval=args.get("interval", "1d"), period=args.get("period", "2y"))
    candles = (h or {}).get("candles") or []
    return {"symbol": args["symbol"], "n_candles": len(candles), "last": candles[-1] if candles else None}


async def _sources(args: dict) -> dict:
    return await market_data.sources_status()


async def _market_status(args: dict) -> dict:
    return await market_data.status()


async def _search_instruments(args: dict) -> dict:
    from app.services.data.universe import search_symbols

    return {"results": search_symbols(args.get("query", ""), market=args.get("market"), limit=args.get("limit", 10))}


async def _run_backtest(args: dict) -> dict:
    h = await market_data.get_history_auto(args["symbol"], interval=args.get("interval", "1d"), period=args.get("period", "3y"))
    df = to_dataframe(sanitize_history(h))
    if df.empty:
        return {"error": "no data", "symbol": args["symbol"]}
    return run_backtest(
        df,
        strategy=args.get("strategy", "moving_average_crossover"),
        params=args.get("params", {}) or {},
        initial_capital=args.get("initial_capital", 100000.0),
        interval=args.get("interval", "1d"),
        run_validation=bool(args.get("run_validation", False)),
    )


async def _backtest_strategies(args: dict) -> dict:
    return {"strategies": list_strategies()}


async def _monte_carlo(args: dict) -> dict:
    return monte_carlo(args["returns"], n_sims=args.get("n_sims", 1000), horizon=args.get("horizon", 252), initial_capital=args.get("initial_capital", 100000.0))


async def _bootstrap(args: dict) -> dict:
    return bootstrap_metrics(args["returns"], n_boot=args.get("n_boot", 1000))


async def _walk_forward(args: dict) -> dict:
    return walk_forward(args["returns"], n_folds=args.get("n_folds", 4), train_ratio=args.get("train_ratio", 0.7))


async def _risk_xray(args: dict) -> dict:
    return risk_xray(args["returns"])


async def _optimize(args: dict) -> dict:
    return optimize(args["returns"], method=args.get("method", "max_sharpe"), risk_free=args.get("risk_free", 0.05))


async def _india_cost(args: dict) -> dict:
    return india_cost_config(intraday=bool(args.get("intraday", False))).as_dict()


async def _metrics(args: dict) -> dict:
    from app.services.backtesting.metrics import compute_metrics, to_returns

    equity = args.get("equity") or []
    if not equity:
        return {"error": "equity list required"}
    import numpy as np

    eq = np.asarray(equity, dtype=float)
    return compute_metrics(eq, to_returns(eq), interval=args.get("interval", "1d"), initial_capital=eq[0])


async def _factors_list(args: dict) -> dict:
    return {"count": count_factors(), "factors": list_factors()}


async def _alpha101(args: dict) -> dict:
    h = await market_data.get_history_auto(args["symbol"], interval=args.get("interval", "1d"), period=args.get("period", "1y"))
    df = to_dataframe(sanitize_history(h))
    if df.empty:
        return {"error": "no data"}
    name = args.get("factor", "alpha101_001")
    out = compute_factor(df, name)
    return {"factor": name, "latest": float(out.dropna().iloc[-1]) if out.dropna().shape[0] else None}


async def _ic(args: dict) -> dict:
    data = {s: await market_data.get_history_auto(s, interval=args.get("interval", "1d"), period=args.get("period", "2y")) for s in args["symbols"]}
    panel = build_panel(data, args.get("factors") or ["alpha101_001"])
    return ic_analysis(panel, args.get("factors") or ["alpha101_001"], args.get("forward_days", 1))


async def _quantile(args: dict) -> dict:
    data = {s: await market_data.get_history_auto(s, interval="1d", period=args.get("period", "2y")) for s in args["symbols"]}
    panel = build_panel(data, args.get("factors") or ["alpha101_001"])
    return quantile_returns(panel, args.get("factors") or ["alpha101_001"], args.get("n_quantiles", 5))


async def _bench(args: dict) -> dict:
    data = {s: await market_data.get_history_auto(s, interval="1d", period=args.get("period", "2y")) for s in args["symbols"]}
    panel = build_panel(data, [args["factor"]])
    return factor_bench(panel, args["factor"], args.get("n_quantiles", 5))


async def _blend(args: dict) -> dict:
    data = {s: await market_data.get_history_auto(s, interval="1d", period=args.get("period", "2y")) for s in args["symbols"]}
    panel = build_panel(data, list(args["weights"]))
    panel["composite"] = composite_signal(panel, args["weights"], args.get("method", "rank"))
    return factor_portfolio_backtest(panel, "composite", n_quantiles=args.get("n_quantiles", 5), long_only=bool(args.get("long_only", True)))


async def _param_var(args: dict) -> dict:
    return parametric_var(args["returns"], args.get("level", 0.05), args.get("horizon", 1))


async def _cornish_var(args: dict) -> dict:
    return cornish_fisher_var(args["returns"], args.get("level", 0.05))


async def _evt_var(args: dict) -> dict:
    return evt_var(args["returns"], args.get("level", 0.05), args.get("threshold_pct", 0.95))


async def _ewma(args: dict) -> dict:
    return ewma_vol(args["returns"], args.get("lambda", 0.94))


async def _black_litterman(args: dict) -> dict:
    return black_litterman(args["returns_mean"], args["cov"], args["market_weights"], args.get("views", []), risk_free=args.get("risk_free", 0.0), tau=args.get("tau", 0.05))


async def _brinson(args: dict) -> dict:
    return brinson_attribution(args["portfolio_returns"], args["benchmark_returns"], args["portfolio_weights"], args["benchmark_weights"])


async def _npv(args: dict) -> dict:
    return {"npv": npv(args["rate"], args["amounts"])}


async def _irr(args: dict) -> dict:
    try:
        return {"irr": irr(args["amounts"])}
    except ValueError as exc:
        return {"error": str(exc)}


async def _xirr(args: dict) -> dict:
    try:
        return {"xirr": xirr(args["amounts"], args["dates"])}
    except ValueError as exc:
        return {"error": str(exc)}


async def _implied_vol(args: dict) -> dict:
    return {"implied_volatility": iv_fn(args["market_price"], args["spot"], args["strike"], args["time_to_expiry"], args.get("option_type", "call"))}


async def _greeks(args: dict) -> dict:
    return greeks_fn(args["spot"], args["strike"], args["time_to_expiry"], args["volatility"], args.get("option_type", "call"))


async def _indicators(args: dict) -> dict:
    h = await market_data.get_history_auto(args["symbol"], interval=args.get("interval", "1d"), period=args.get("period", "1y"))
    df = to_dataframe(sanitize_history(h))
    if df.empty:
        return {"error": "no data"}
    res = TechnicalIndicators.analyze_all({"close": df["close"].tolist(), "high": df["high"].tolist(), "low": df["low"].tolist(), "volume": df["volume"].tolist()})
    return {k: {"value": v.value, "signal": v.signal, "strength": v.strength} for k, v in res.items()}


async def _grounding(args: dict) -> dict:
    return grounding_gate.verify(args["text"], args["facts"])


async def _presets(args: dict) -> dict:
    return {"presets": list_presets()}


async def _preset_dag(args: dict) -> dict:
    return build_dag(args["preset"], args.get("params"))


async def _memory_set(args: dict) -> dict:
    from app.services.memory.store import memory_store

    return await memory_store.set(args["user_id"], args["key"], args["value"], kind=args.get("kind", "note"), scope=args.get("scope", ""))


async def _memory_get(args: dict) -> dict:
    from app.services.memory.store import memory_store

    return await memory_store.get(args["user_id"], args["key"]) or {"found": False}


async def _memory_list(args: dict) -> dict:
    from app.services.memory.store import memory_store

    return {"memories": await memory_store.list(args["user_id"], kind=args.get("kind"), scope=args.get("scope"))}


async def _memory_delete(args: dict) -> dict:
    from app.services.memory.store import memory_store

    return {"deleted": await memory_store.delete(args["user_id"], args["key"])}


async def _schedule_create(args: dict) -> dict:
    from app.services.scheduler.service import scheduled_research_service

    return await scheduled_research_service.create(args["user_id"], args["name"], args["playbook"], args["cron_expr"], args.get("timezone", "UTC"))


async def _schedule_list(args: dict) -> dict:
    from app.services.scheduler.service import scheduled_research_service

    return {"schedules": await scheduled_research_service.list(args["user_id"])}


async def _schedule_delete(args: dict) -> dict:
    from app.services.scheduler.service import scheduled_research_service

    return {"deleted": await scheduled_research_service.delete(args["user_id"], args["schedule_id"])}


async def _schedule_run(args: dict) -> dict:
    from app.services.scheduler.service import scheduled_research_service
    from app.services.scheduler.runner import run_playbook

    schedule = await scheduled_research_service.get(args["user_id"], args["schedule_id"])
    if schedule is None:
        return {"error": "schedule not found"}
    result = await run_playbook(schedule["playbook"])
    await scheduled_research_service.mark_run(args["schedule_id"], {"status": "error" if "error" in result else "done", "output": result})
    return result


async def _schedule_next(args: dict) -> dict:
    from app.services.scheduler.cron import next_occurrence, parse_cron
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(args.get("timezone", "UTC"))
    return {"next_run": next_occurrence(parse_cron(args["cron_expr"]), args["after"]).replace(tzinfo=tz).isoformat()}


async def _option_chain(args: dict) -> dict:
    chain = await market_data.get_option_chain(args["symbol"])
    return {"expiries": list(getattr(chain, "expiries", []) or []), "strikes": getattr(chain, "strikes", None), "quote": getattr(chain, "quote", None)}


async def _prediction(args: dict) -> dict:
    from app.services.prediction.engine import engine as prediction_engine

    result = await prediction_engine.predict(args["symbol"], use_agent=False)
    return result.to_dict() if hasattr(result, "to_dict") else vars(result)


async def _scanner(args: dict) -> dict:
    from app.services.scanners.engine import engine as scanner_engine

    return await scanner_engine.scan(args.get("scanner_type", "momentum_breakout"))


async def _sectors(args: dict) -> dict:
    from app.services.analysis.sectors import get_sector_analysis

    return await get_sector_analysis()


async def _status_probe(args: dict) -> dict:
    return await market_data.status()


async def _fundamentals(args: dict) -> dict:
    return await market_data.get_fundamentals(args["symbol"], args.get("provider"))


async def _indices(args: dict) -> dict:
    from app.services.data.universe import indices

    return {"indices": indices(args.get("market", "india"))}


async def _market_list(args: dict) -> dict:
    from app.services.data.universe import by_market

    return {"symbols": by_market(args.get("market", "india"))}


async def _cvar(args: dict) -> dict:
    from app.services.backtesting.metrics import cvar_historical

    return {"cvar": cvar_historical(args["returns"], args.get("level", 0.05))}


async def _indicator_single(args: dict) -> dict:
    h = await market_data.get_history_auto(args["symbol"], interval=args.get("interval", "1d"), period=args.get("period", "1y"))
    df = to_dataframe(sanitize_history(h))
    if df.empty:
        return {"error": "no data"}
    close = df["close"].tolist()
    name = args.get("indicator", "rsi")
    fns = {"rsi": TechnicalIndicators.rsi, "sma20": lambda c: TechnicalIndicators.sma(c, 20), "sma50": lambda c: TechnicalIndicators.sma(c, 50), "ema20": lambda c: TechnicalIndicators.ema(c, 20)}
    if name not in fns:
        return {"error": f"unknown indicator '{name}'", "available": sorted(fns)}
    return {"indicator": name, "value": float(fns[name](close))}


async def _swarm_run(args: dict) -> dict:
    from app.services.scheduler.runner import run_playbook

    return await run_playbook({"type": "swarm", "preset": args["preset"], "symbols": args["symbols"]})


async def _playbook_run(args: dict) -> dict:
    from app.services.scheduler.runner import run_playbook

    return await run_playbook(args["playbook"])


async def _factor_panel(args: dict) -> dict:
    data = {s: await market_data.get_history_auto(s, interval="1d", period=args.get("period", "2y")) for s in args["symbols"]}
    panel = build_panel(data, args["factors"])
    if panel.empty:
        return {"error": "no panel"}
    latest = panel.groupby(level=0).last()
    return {"latest": {s: {f: (float(latest.loc[s, f]) if latest.loc[s, f] == latest.loc[s, f] else None) for f in args["factors"]} for s in args["symbols"] if s in latest.index}}


async def _candle_stats(args: dict) -> dict:
    h = await market_data.get_history_auto(args["symbol"], interval=args.get("interval", "1d"), period=args.get("period", "1y"))
    candles = (h or {}).get("candles") or []
    if len(candles) < 30:
        return {"error": "not enough candles", "n": len(candles)}
    closes = [c["close"] for c in candles]
    return {
        "symbol": args["symbol"],
        "n": len(candles),
        "last_close": closes[-1],
        "high_52w": max(c["high"] for c in candles),
        "low_52w": min(c["low"] for c in candles),
        "change_1m_pct": round((closes[-1] / closes[-22] - 1) * 100, 3) if len(closes) > 22 else None,
    }


async def _trades_summary(args: dict) -> dict:
    from app.services.backtesting.metrics import summarize_trades

    return summarize_trades(args["trades"])


async def _historical_var(args: dict) -> dict:
    from app.services.backtesting.metrics import var_historical

    return {"var": var_historical(args["returns"], args.get("level", 0.05))}


async def _indicator_chart(args: dict) -> dict:
    from app.services.technical.indicators import TechnicalIndicators as TI

    h = await market_data.get_history_auto(args["symbol"], interval=args.get("interval", "1d"), period=args.get("period", "1y"))
    df = to_dataframe(sanitize_history(h))
    if df.empty:
        return {"error": "no data"}
    close = df["close"].tolist()
    return {
        "symbol": args["symbol"],
        "dates": [str(d)[:10] for d in df.index.tolist()],
        "close": [round(float(x), 4) for x in close],
        "sma20": [round(float(x), 4) if x == x else None for x in TI.sma(close, 20)],
        "rsi": TI.rsi(close),
        "macd_hist": TI.macd(close)["histogram"],
    }


async def _theoretical_price(args: dict) -> dict:
    from app.services.quantlib.options import greeks as greeks_fn

    g = greeks_fn(args["spot"], args["strike"], args["time_to_expiry"], args["volatility"], args.get("option_type", "call"))
    return {"price": g["price"], "greeks": g}


async def _due_tasks(args: dict) -> dict:
    from app.services.scheduler.service import scheduled_research_service

    return {"due": await scheduled_research_service.due_tasks()}


# name -> (description, input_schema, handler)
TOOLS: dict[str, tuple[str, dict, Any]] = {
    "market.quote": ("Live quote for a symbol", {"type": "object", "properties": {"symbol": {"type": "string"}, "provider": {"type": "string"}}, "required": ["symbol"]}, _quote),
    "market.history": ("OHLCV candle history", {"type": "object", "properties": {"symbol": {"type": "string"}, "interval": {"type": "string"}, "period": {"type": "string"}}, "required": ["symbol"]}, _history),
    "market.sources": ("Provider health readout", {"type": "object", "properties": {}}, _sources),
    "market.status": ("Provider reachability + capabilities", {"type": "object", "properties": {}}, _market_status),
    "market.search": ("Search the symbol universe", {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}, _search_instruments),
    "backtest.run": ("Run a backtest v2 with costs/validation", {"type": "object", "properties": {"symbol": {"type": "string"}, "strategy": {"type": "string"}, "params": {"type": "object"}, "initial_capital": {"type": "number"}, "interval": {"type": "string"}, "period": {"type": "string"}, "run_validation": {"type": "boolean"}}, "required": ["symbol"]}, _run_backtest),
    "backtest.strategies": ("List built-in strategies", {"type": "object", "properties": {}}, _backtest_strategies),
    "backtest.monte_carlo": ("Monte-Carlo confidence intervals", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "n_sims": {"type": "integer"}, "horizon": {"type": "integer"}, "initial_capital": {"type": "number"}}, "required": ["returns"]}, _monte_carlo),
    "backtest.bootstrap": ("Bootstrap metric confidence intervals", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "n_boot": {"type": "integer"}}, "required": ["returns"]}, _bootstrap),
    "backtest.walk_forward": ("Walk-forward out-of-sample validation", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "n_folds": {"type": "integer"}, "train_ratio": {"type": "number"}}, "required": ["returns"]}, _walk_forward),
    "backtest.risk_xray": ("Risk x-ray of a returns series", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}}, "required": ["returns"]}, _risk_xray),
    "backtest.optimize_portfolio": ("Equal/min-var/max-sharpe/risk-parity weights", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "array"}}, "method": {"type": "string"}, "risk_free": {"type": "number"}}, "required": ["returns"]}, _optimize),
    "backtest.india_cost_config": ("Indian equity cost config (STT/stamp/SEBI/GST)", {"type": "object", "properties": {"intraday": {"type": "boolean"}}}, _india_cost),
    "backtest.metrics": ("Full metrics block from an equity curve", {"type": "object", "properties": {"equity": {"type": "array", "items": {"type": "number"}}, "interval": {"type": "string"}}, "required": ["equity"]}, _metrics),
    "factors.list": ("List all computable factors", {"type": "object", "properties": {}}, _factors_list),
    "factors.alpha101": ("Compute one Kakushadze alpha for a symbol", {"type": "object", "properties": {"symbol": {"type": "string"}, "factor": {"type": "string"}, "interval": {"type": "string"}, "period": {"type": "string"}}, "required": ["symbol"]}, _alpha101),
    "factors.ic": ("Rank IC/ICIR of factors across symbols", {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}}, "factors": {"type": "array", "items": {"type": "string"}}, "forward_days": {"type": "integer"}}, "required": ["symbols"]}, _ic),
    "factors.quantiles": ("Mean forward return per factor quantile", {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}}, "factors": {"type": "array", "items": {"type": "string"}}, "n_quantiles": {"type": "integer"}}, "required": ["symbols"]}, _quantile),
    "factors.bench": ("Long-short factor benchmark", {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}}, "factor": {"type": "string"}, "n_quantiles": {"type": "integer"}}, "required": ["symbols", "factor"]}, _bench),
    "factors.blend": ("Composite-signal portfolio backtest", {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}}, "weights": {"type": "object"}, "method": {"type": "string"}, "n_quantiles": {"type": "integer"}, "long_only": {"type": "boolean"}}, "required": ["symbols", "weights"]}, _blend),
    "quantlib.parametric_var": ("Variance-covariance VaR", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "level": {"type": "number"}, "horizon": {"type": "integer"}}, "required": ["returns"]}, _param_var),
    "quantlib.cornish_fisher_var": ("Skew/kurtosis-adjusted VaR", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "level": {"type": "number"}}, "required": ["returns"]}, _cornish_var),
    "quantlib.evt_var": ("Peaks-over-threshold EVT VaR/ES", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "level": {"type": "number"}, "threshold_pct": {"type": "number"}}, "required": ["returns"]}, _evt_var),
    "quantlib.ewma_vol": ("RiskMetrics EWMA volatility", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "lambda": {"type": "number"}}, "required": ["returns"]}, _ewma),
    "quantlib.black_litterman": ("BL posterior returns from views", {"type": "object", "properties": {"returns_mean": {"type": "object"}, "cov": {"type": "array", "items": {"type": "array"}}, "market_weights": {"type": "object"}, "views": {"type": "array"}, "risk_free": {"type": "number"}, "tau": {"type": "number"}}, "required": ["returns_mean", "cov", "market_weights"]}, _black_litterman),
    "quantlib.brinson": ("Brinson attribution", {"type": "object", "properties": {"portfolio_returns": {"type": "object"}, "benchmark_returns": {"type": "object"}, "portfolio_weights": {"type": "object"}, "benchmark_weights": {"type": "object"}}, "required": ["portfolio_returns", "benchmark_returns", "portfolio_weights", "benchmark_weights"]}, _brinson),
    "quantlib.npv": ("Net present value", {"type": "object", "properties": {"rate": {"type": "number"}, "amounts": {"type": "array", "items": {"type": "number"}}}, "required": ["rate", "amounts"]}, _npv),
    "quantlib.irr": ("Internal rate of return", {"type": "object", "properties": {"amounts": {"type": "array", "items": {"type": "number"}}}, "required": ["amounts"]}, _irr),
    "quantlib.xirr": ("Exact-date IRR", {"type": "object", "properties": {"amounts": {"type": "array", "items": {"type": "number"}}, "dates": {"type": "array", "items": {"type": "string"}}}, "required": ["amounts", "dates"]}, _xirr),
    "quantlib.implied_vol": ("Black-Scholes implied volatility", {"type": "object", "properties": {"market_price": {"type": "number"}, "spot": {"type": "number"}, "strike": {"type": "number"}, "time_to_expiry": {"type": "number"}, "option_type": {"type": "string"}}, "required": ["market_price", "spot", "strike", "time_to_expiry"]}, _implied_vol),
    "quantlib.greeks": ("Option greeks surface", {"type": "object", "properties": {"spot": {"type": "number"}, "strike": {"type": "number"}, "time_to_expiry": {"type": "number"}, "volatility": {"type": "number"}, "option_type": {"type": "string"}}, "required": ["spot", "strike", "time_to_expiry", "volatility"]}, _greeks),
    "indicators.analyze_all": ("SMA/RSI/MACD/Bollinger signals", {"type": "object", "properties": {"symbol": {"type": "string"}, "interval": {"type": "string"}, "period": {"type": "string"}}, "required": ["symbol"]}, _indicators),
    "grounding.verify": ("Verify LLM claims against facts", {"type": "object", "properties": {"text": {"type": "string"}, "facts": {"type": "array", "items": {"type": "object"}}}, "required": ["text", "facts"]}, _grounding),
    "swarm.presets": ("List 30 swarm DAG presets", {"type": "object", "properties": {}}, _presets),
    "swarm.dag": ("Get one preset as a DAG", {"type": "object", "properties": {"preset": {"type": "string"}, "params": {"type": "object"}}, "required": ["preset"]}, _preset_dag),
    "memory.set": ("Persist a memory for a user", {"type": "object", "properties": {"user_id": {"type": "string"}, "key": {"type": "string"}, "value": {}, "kind": {"type": "string"}, "scope": {"type": "string"}}, "required": ["user_id", "key", "value"]}, _memory_set),
    "memory.get": ("Read a memory", {"type": "object", "properties": {"user_id": {"type": "string"}, "key": {"type": "string"}}, "required": ["user_id", "key"]}, _memory_get),
    "memory.list": ("List memories", {"type": "object", "properties": {"user_id": {"type": "string"}, "kind": {"type": "string"}, "scope": {"type": "string"}}, "required": ["user_id"]}, _memory_list),
    "memory.delete": ("Delete a memory", {"type": "object", "properties": {"user_id": {"type": "string"}, "key": {"type": "string"}}, "required": ["user_id", "key"]}, _memory_delete),
    "scheduler.create": ("Create a cron research schedule", {"type": "object", "properties": {"user_id": {"type": "string"}, "name": {"type": "string"}, "playbook": {"type": "object"}, "cron_expr": {"type": "string"}, "timezone": {"type": "string"}}, "required": ["user_id", "name", "playbook", "cron_expr"]}, _schedule_create),
    "scheduler.list": ("List schedules", {"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]}, _schedule_list),
    "scheduler.delete": ("Delete a schedule", {"type": "object", "properties": {"user_id": {"type": "string"}, "schedule_id": {"type": "string"}}, "required": ["user_id", "schedule_id"]}, _schedule_delete),
    "scheduler.run_now": ("Execute a schedule's playbook immediately", {"type": "object", "properties": {"user_id": {"type": "string"}, "schedule_id": {"type": "string"}}, "required": ["user_id", "schedule_id"]}, _schedule_run),
    "scheduler.next_run": ("Next cron occurrence in an IANA timezone", {"type": "object", "properties": {"cron_expr": {"type": "string"}, "after": {"type": "string"}, "timezone": {"type": "string"}}, "required": ["cron_expr", "after"]}, _schedule_next),
    "options.chain": ("Real options chain (strikes/expiries/quote)", {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}, _option_chain),
    "prediction.predict": ("Deterministic prediction factors for a symbol", {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}, _prediction),
    "scanner.scan": ("Run a scanner over the universe", {"type": "object", "properties": {"scanner_type": {"type": "string"}}}, _scanner),
    "market.sectors": ("Sector & cap-class analysis", {"type": "object", "properties": {}}, _sectors),
    "market.fundamentals": ("Real fundamentals for a symbol", {"type": "object", "properties": {"symbol": {"type": "string"}, "provider": {"type": "string"}}, "required": ["symbol"]}, _fundamentals),
    "market.indices": ("List index symbols for a market", {"type": "object", "properties": {"market": {"type": "string"}}}, _indices),
    "market.list": ("List universe symbols for a market", {"type": "object", "properties": {"market": {"type": "string"}}}, _market_list),
    "quantlib.cvar": ("Historical expected shortfall", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "level": {"type": "number"}}, "required": ["returns"]}, _cvar),
    "indicators.single": ("Compute one indicator (rsi/sma20/sma50/ema20)", {"type": "object", "properties": {"symbol": {"type": "string"}, "indicator": {"type": "string"}, "interval": {"type": "string"}, "period": {"type": "string"}}, "required": ["symbol", "indicator"]}, _indicator_single),
    "swarm.run": ("Execute a swarm preset deterministically", {"type": "object", "properties": {"preset": {"type": "string"}, "symbols": {"type": "array", "items": {"type": "string"}}}, "required": ["preset", "symbols"]}, _swarm_run),
    "scheduler.playbook": ("Run any playbook directly", {"type": "object", "properties": {"playbook": {"type": "object"}}, "required": ["playbook"]}, _playbook_run),
    "factors.panel": ("Latest factor values per symbol", {"type": "object", "properties": {"symbols": {"type": "array", "items": {"type": "string"}}, "factors": {"type": "array", "items": {"type": "string"}}, "period": {"type": "string"}}, "required": ["symbols", "factors"]}, _factor_panel),
    "market.candle_stats": ("High-level stats from a candle history", {"type": "object", "properties": {"symbol": {"type": "string"}, "interval": {"type": "string"}, "period": {"type": "string"}}, "required": ["symbol"]}, _candle_stats),
    "backtest.trades": ("Trade summary stats (profit factor, win rate)", {"type": "object", "properties": {"trades": {"type": "array", "items": {"type": "object"}}}, "required": ["trades"]}, _trades_summary),
    "quantlib.historical_var": ("Historical percentile VaR", {"type": "object", "properties": {"returns": {"type": "array", "items": {"type": "number"}}, "level": {"type": "number"}}, "required": ["returns"]}, _historical_var),
    "indicators.chart": ("Indicator series for charting", {"type": "object", "properties": {"symbol": {"type": "string"}, "interval": {"type": "string"}, "period": {"type": "string"}}, "required": ["symbol"]}, _indicator_chart),
    "options.theoretical_price": ("Black-Scholes price + greeks", {"type": "object", "properties": {"spot": {"type": "number"}, "strike": {"type": "number"}, "time_to_expiry": {"type": "number"}, "volatility": {"type": "number"}, "option_type": {"type": "string"}}, "required": ["spot", "strike", "time_to_expiry", "volatility"]}, _theoretical_price),
    "scheduler.due_tasks": ("Enabled schedules due for execution", {"type": "object", "properties": {}}, _due_tasks),
}

assert len(TOOLS) == 62, f"expected 62 tools, got {len(TOOLS)}"

TOOL_LIST = [
    {
        "name": name,
        "description": desc,
        "inputSchema": schema,
    }
    for name, (desc, schema, _h) in sorted(TOOLS.items())
]
