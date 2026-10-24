"""`stockos` CLI command implementations.

Every command runs the **same real StockOS services the API routes use** -
there is no separate "CLI data path" and no fabricated numbers. Output is
printed through Rich panels/tables so long LLM markdown and numeric reports
stay readable on any terminal.

Persistence rules (honest, additive):
- ``desk`` writes the run to the per-user ``trading_runs`` table **only when**
  ``--user`` resolves to an existing registered user (the column has a FK to
  ``users.id``). All desk runs are always recorded in the append-only decision
  log under ``ta_data_root`` (the engine does this itself).
- The other commands are read-only analysis: they print results but never
  invent rows.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from typing import Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import or_, select

from app.core.config import settings
from app.db.models import User
from app.db.session import SessionFactory
from app.services.backtesting.costs import india_cost_config
from app.services.backtesting.engine_v2 import BacktestRequest, run_backtest_with_benchmark
from app.services.data.ohlcv import sanitize_history, to_dataframe
from app.services.data.service import market_data
from app.services.factors.analysis import build_panel, ic_analysis
from app.services.factors.registry import count_factors, list_factors
from app.services.prediction.engine import PredictionEngine, Timeframe
from app.services.tradingagents import store
from app.services.tradingagents.config_port import build_engine_config
from app.services.tradingagents.data_port import to_engine_symbol
from app.services.tradingagents.engine import TradingDeskEngine
from app.services.tradingagents.llm_port import LLMSelection, PROVIDERS, validate_selection

console = Console()

# `stockos predict` timeframe shorthand, mirroring the API router's map.
_TIME_FRAME_MAP = {
    "1D": "TOMORROW",
    "1W": "WEEK",
    "1M": "MONTH",
    "3M": "QUARTER",
    "6M": "HALF_YEAR",
    "1Y": "YEAR",
    "3Y": "THREE_YEARS",
    "5Y": "FIVE_YEARS",
}

_BACKTEST_INTERVALS = "1m,5m,15m,30m,1h,4h,1d,1w,1M"
_BACKTEST_PERIODS = "5d,1mo,3mo,6mo,1y,2y,5y,10y,max"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "-"


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _timeframe(name: str) -> Timeframe:
    key = _TIME_FRAME_MAP.get((name or "").upper())
    if key is None:
        raise typer.BadParameter(
            f"invalid timeframe '{name}' (choose from {', '.join(_TIME_FRAME_MAP)})"
        )
    return Timeframe[key]


# --- status -------------------------------------------------------------------


async def _status() -> dict[str, Any]:
    status = await market_data.provider_status()
    return {
        "providers": status,
        "factor_count": count_factors(),
        "llm_default_provider": settings.llm_default_provider or "ollama",
        "ta_default_provider": settings.ta_default_provider,
    }


def status_cmd() -> None:
    """Live provider health + platform registry readout."""
    info = asyncio.run(_status())

    providers = info["providers"]
    table = Table(title="Data providers (live probe)", header_style="bold magenta")
    table.add_column("Provider", style="cyan")
    table.add_column("Reachable", justify="center")
    table.add_column("Default for", style="green")
    table.add_column("Capabilities", overflow="fold")
    for name, meta in providers.items():
        table.add_row(
            name,
            ("[green]yes[/green]" if meta.get("reachable") else "[red]no[/red]"),
            ", ".join(meta.get("default_for") or ["-"]),
            ", ".join(meta.get("capabilities") or ["-"]),
        )
    console.print(table)
    console.print(
        Panel(
            (
                f"[bold]Factors[/bold] (alpha101): {info['factor_count']}\n"
                f"[bold]LLM default provider[/bold]: {info['llm_default_provider']}\n"
                f"[bold]Trading Desk default provider[/bold]: {info['ta_default_provider']}\n"
                f"[bold]Data root[/bold]: {settings.ta_data_root}"
            ),
            title="Platform",
            border_style="blue",
        )
    )


# --- predict ------------------------------------------------------------------


async def _predict(symbol: str, timeframe: str, option: dict | None) -> dict:
    engine = PredictionEngine(market_service=market_data)
    return await engine.predict(symbol, _timeframe(timeframe), use_agent=True, option=option)


def predict_cmd(
    symbol: str,
    timeframe: str,
    option_type: str | None,
    strike: float | None,
    expiry: str | None,
) -> None:
    """Predict a price for SYMBOL (deterministic engine + LLM agent view)."""
    option = None
    if option_type or strike is not None:
        option = {"type": (option_type or "CE").upper(), "strike": strike, "expiry": expiry}
    try:
        r = asyncio.run(_predict(symbol, timeframe, option))
    except Exception as exc:  # noqa: BLE001
        raise typer.Exit(f"prediction failed: {exc}") from exc

    grid = Table(show_header=False, box=None, padding=(0, 3))
    grid.add_column(style="bold cyan")
    grid.add_column(style="white")
    grid.add_row("Symbol", r.symbol)
    grid.add_row("Current", _money(r.current_price))
    grid.add_row("Predicted", _money(r.predicted_price))
    grid.add_row("Expected return", _pct(r.expected_return))
    grid.add_row("Confidence", f"{r.confidence:.0%}" if r.confidence else "-")
    grid.add_row("Action", getattr(r, "action", "-") or "-")
    grid.add_row("Horizon", getattr(r, "horizon", "-") or "-")
    grid.add_row("Base case", _money(getattr(r, "base_case", None)))
    grid.add_row("Bull case", _money(getattr(r, "bull_case", None)))
    grid.add_row("Bear case", _money(getattr(r, "bear_case", None)))
    console.print(Panel(grid, title=f"Prediction - {symbol}", border_style="green"))

    reasoning = getattr(r, "reasoning", "") or ""
    if reasoning:
        console.print(Panel(Markdown(reasoning), title="Reasoning", border_style="blue"))


# --- backtest -----------------------------------------------------------------


async def _backtest(
    symbol: str,
    strategy: str,
    interval: str,
    period: str,
    benchmark: str | None,
    validate: bool,
    params_json: str | None,
    initial_capital: float,
    intraday: bool,
) -> dict:
    params: dict[str, Any] = {}
    if params_json:
        try:
            parsed = json.loads(params_json)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"--params is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise typer.BadParameter("--params must be a JSON object")
        params = parsed

    req = BacktestRequest(
        symbol=symbol,
        interval=interval,
        period=period,
        strategy=strategy,
        params=params,
        initial_capital=initial_capital,
        costs=india_cost_config(intraday=intraday),
        benchmark_symbol=benchmark,
        validate=validate,
    )
    history = await market_data.get_history_auto(symbol, interval=interval, period=period)
    history = sanitize_history(history)
    df = to_dataframe(history)
    if df is None or df.empty:
        raise typer.Exit(
            f"no price history for {symbol} ({history.get('error') or history.get('source') or 'no source'})"
        )
    bench_df = None
    if benchmark:
        try:
            bench = await market_data.get_history_auto(benchmark, interval=interval, period=period)
            bench_df = to_dataframe(sanitize_history(bench))
            if bench_df is None or bench_df.empty:
                bench_df = None
        except Exception:  # noqa: BLE001 - honest degradation: benchmark omitted
            bench_df = None
    return run_backtest_with_benchmark(df, bench_df, req)


def backtest_cmd(
    symbol: str,
    strategy: str,
    interval: str,
    period: str,
    benchmark: str | None,
    validate: bool,
    params_json: str | None,
    initial_capital: float,
    intraday: bool,
) -> None:
    """Run a bar-level backtest on real candles (fills at next open)."""
    try:
        r = asyncio.run(
            _backtest(
                symbol, strategy, interval, period, benchmark, validate, params_json, initial_capital, intraday
            )
        )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise typer.Exit(f"backtest failed: {exc}") from exc

    m = r.get("metrics", {})
    grid = Table(show_header=False, box=None, padding=(0, 3))
    grid.add_column(style="bold cyan")
    grid.add_column(style="white")
    grid.add_row("Strategy", f"{r.get('strategy')} {r.get('params') or ''}".strip())
    grid.add_row("Interval", f"{r.get('interval')} - {len(r.get('dates') or [])} bars")
    grid.add_row("Initial capital", _money(m.get("initial_capital")))
    grid.add_row("Final equity", _money(m.get("final_equity")))
    grid.add_row("Total return", _pct(m.get("total_return")))
    grid.add_row("Annualized return", _pct(m.get("annualized_return")))
    grid.add_row("Sharpe", f"{m.get('sharpe_ratio', 0):.2f}")
    grid.add_row("Sortino", f"{m.get('sortino_ratio', 0):.2f}")
    grid.add_row("Calmar", f"{m.get('calmar_ratio', 0):.2f}")
    grid.add_row("Max drawdown", _pct(m.get("max_drawdown")))
    grid.add_row("Volatility (ann.)", _pct(m.get("annualized_vol")))
    grid.add_row("Var 95 / CVaR 95", f"{_pct(m.get('var_95'))} / {_pct(m.get('cvar_95'))}")
    grid.add_row("Trades", str((m.get("trades") or {}).get("total_trades", "-")))
    grid.add_row("Win rate", _pct((m.get("trades") or {}).get("win_rate")))
    console.print(Panel(grid, title=f"Backtest - {symbol}", border_style="green"))

    bench = r.get("benchmark")
    if bench:
        console.print(
            Panel(
                Markdown(
                    f"Benchmark `{bench.get('symbol')}`: total return **{_pct(bench.get('total_return'))}**, "
                    f"final value **{_money(bench.get('end_value'))}**"
                ),
                title="Benchmark",
                border_style="blue",
            )
        )


# --- factors ------------------------------------------------------------------


async def _factors(
    symbols: list[str],
    factor: str | None,
    interval: str,
    period: str,
    forward_days: int,
) -> dict:
    histories: dict[str, dict] = {}
    failures: list[str] = []
    for symbol in symbols:
        try:
            history = await market_data.get_history_auto(symbol, interval=interval, period=period)
            history = sanitize_history(history)
            if history.get("candles"):
                histories[symbol] = history
            else:
                failures.append(f"{symbol} (no data)")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{symbol} ({type(exc).__name__})")
    if not histories:
        raise typer.Exit(f"no usable data for any symbol ({', '.join(failures) or 'empty list'})")
    factors = [factor] if factor else None
    panel = build_panel(histories, factors)
    if panel.empty:
        raise typer.Exit(f"panel build produced no data ({', '.join(failures) or 'unknown'})")
    names = factors or [c for c in panel.columns if c.startswith("alpha101_")]
    unknown = [f for f in names if f not in panel.columns]
    if unknown:
        raise typer.Exit(f"unknown factor(s): {', '.join(unknown)}")
    ic = ic_analysis(panel, names, forward_days)
    return {"symbols": list(histories), "failures": failures, "interval": interval, "ic": ic}


def factors_cmd(
    symbols: list[str],
    factor: str | None,
    interval: str,
    period: str,
    forward_days: int,
) -> None:
    """Per-factor rank IC over a real symbol panel."""
    try:
        r = asyncio.run(_factors(symbols, factor, interval, period, forward_days))
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise typer.Exit(f"factor analysis failed: {exc}") from exc

    ic_factors = (r["ic"].get("factors") or {})
    table = Table(title="Factor IC", header_style="bold magenta")
    table.add_column("Factor", style="cyan")
    table.add_column("IC mean", justify="right")
    table.add_column("ICIR", justify="right")
    table.add_column("IC std", justify="right")
    table.add_column("Days", justify="right")
    for name, stats in ic_factors.items():
        table.add_row(
            name,
            f"{stats['ic_mean']:.4f}",
            f"{stats['ic_ir']:.3f}",
            f"{stats['ic_std']:.4f}",
            str(stats["n_days"]),
        )
    console.print(table)
    if not ic_factors:
        console.print("[yellow]No factor stats computed (insufficient cross-sections).[/yellow]")
    if r["failures"]:
        console.print(f"[dim]skipped: {', '.join(r['failures'])}[/dim]")


# --- desk ---------------------------------------------------------------------


async def _resolve_user(value: str | None) -> User | None:
    if not value:
        return None
    async with SessionFactory() as session:
        return await session.scalar(
            select(User).where(or_(User.email == value, User.id == value))
        )


async def _desk(
    symbol: str,
    sel: LLMSelection,
    trade_date: str,
    max_debate: int | None,
    max_risk: int | None,
    user: User | None,
) -> dict[str, Any]:
    config = await build_engine_config(
        sel, max_debate_rounds=max_debate, max_risk_rounds=max_risk
    )
    provider = config["llm_provider"]
    deep_model = config["deep_think_llm"]
    quick_model = config["quick_think_llm"]

    run_id = None
    if user is not None:
        async with SessionFactory() as session:
            row = await store.create_run(
                session,
                user_id=user.id,
                symbol=symbol,
                engine_symbol=to_engine_symbol(symbol),
                trade_date=trade_date,
                provider=provider,
                deep_model=deep_model,
                quick_model=quick_model,
            )
            run_id = row.id

    def on_step(node: str, label: str, _state: dict) -> None:
        console.print(f"  [bold cyan]{node}[/bold cyan]: [white]{label}[/white]")

    engine = TradingDeskEngine()
    try:
        result = await engine.run(
            symbol=symbol,
            sel=sel,
            trade_date=trade_date,
            max_debate_rounds=max_debate,
            max_risk_rounds=max_risk,
            on_step=on_step,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        if run_id is not None:
            async with SessionFactory() as session:
                await store.update_run(session, run_id, status="failed", error=str(exc))
        raise typer.Exit(f"trading desk run failed: {exc}") from exc

    if run_id is not None:
        async with SessionFactory() as session:
            updated = await store.update_run(
                session,
                run_id,
                status="completed",
                rating=result["rating"],
                signal=result["signal"],
                final_decision=result["final_decision"],
                reports=result["reports"],
                node_trace=result["node_trace"],
                options=result.get("options"),
            )
            await store.add_run_nodes(session, run_id, result["node_trace"])
            run_id = updated.id if updated else run_id

    result["run_id"] = run_id
    return result


def desk_cmd(
    symbol: str,
    provider: str,
    deep_model: str | None,
    quick_model: str | None,
    api_key: str | None,
    base_url: str | None,
    user: str | None,
    trade_date: str | None,
    max_debate: int | None,
    max_risk: int | None,
) -> None:
    """Run the full Trading Desk (LLM multi-agent) analysis on SYMBOL."""
    sel = LLMSelection(
        provider=provider or settings.ta_default_provider,
        deep_model=deep_model,
        quick_model=quick_model,
        api_key=api_key,
        base_url=base_url,
    )
    errors = validate_selection(sel)
    if errors:
        raise typer.Exit(f"provider '{sel.provider}': {'; '.join(errors)}")

    user_row = asyncio.run(_resolve_user(user))
    if user and user_row is None:
        raise typer.Exit(f"no registered user matches '{user}' (runs need an existing user to persist)")

    today = trade_date or date.today().isoformat()
    console.print(
        Panel(
            Markdown(
                f"- **Symbol**: `{symbol}`\n"
                f"- **Provider**: `{sel.provider}` ({deep_model or 'auto'} / {quick_model or 'auto'})\n"
                f"- **Trade date**: {today}\n"
                f"- **Persist to DB**: {'yes (' + user_row.email + ')' if user_row else 'no (decision log only)'}"
            ),
            title="Trading Desk run",
            border_style="blue",
        )
    )
    try:
        result = asyncio.run(
            _desk(symbol, sel, today, max_debate, max_risk, user_row)
        )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise typer.Exit(f"trading desk run failed: {exc}") from exc

    sig = result.get("signal") or {}
    grid = Table(show_header=False, box=None, padding=(0, 3))
    grid.add_column(style="bold cyan")
    grid.add_column(style="white")
    grid.add_row("Symbol", result.get("symbol"))
    grid.add_row("Rating", f"[bold]{result.get('rating', '-')}[/bold]")
    grid.add_row("Direction", sig.get("direction", "-") or "-")
    grid.add_row("Conviction", _pct(sig.get("conviction")))
    grid.add_row("Price target", _money(sig.get("price_target")))
    if result.get("run_id"):
        grid.add_row("Run id", result["run_id"])
    console.print(Panel(grid, title="Trading Desk result", border_style="green"))

    decision = result.get("final_decision") or ""
    if decision:
        console.print(Panel(Markdown(decision), title="Final decision", border_style="blue"))


# --- runs ---------------------------------------------------------------------


async def _list_runs(user: str, limit: int) -> list[dict]:
    user_row = await _resolve_user(user)
    if user_row is None:
        raise typer.Exit(f"no registered user matches '{user}'")
    async with SessionFactory() as session:
        return await store.list_runs(session, user_row.id, limit=limit)


def runs_cmd(user: str, limit: int) -> None:
    """List the user's persisted Trading Desk runs from the DB."""
    rows = asyncio.run(_list_runs(user, limit))
    if not rows:
        console.print("[yellow]no runs found for this user[/yellow]")
        return
    table = Table(title=f"Trading Desk runs - {user}", header_style="bold magenta")
    table.add_column("Id", style="cyan")
    table.add_column("Symbol", style="green")
    table.add_column("Date", justify="right")
    table.add_column("Status")
    table.add_column("Rating")
    for r in rows:
        table.add_row(r["id"], r["symbol"], r["trade_date"], r["status"], r["rating"] or "-")
    console.print(table)
