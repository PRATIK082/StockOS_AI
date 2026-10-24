"""`stockos` - StockOS command-line interface.

Runs the same real backend services as the web API (market data, prediction,
backtest, factor lab, Trading Desk) from a terminal. Entry point:

    uv run python -m app.cli <command>

or, when installed as a package:

    stockos <command>
"""

from __future__ import annotations

import typer

from app.cli import commands

app = typer.Typer(
    name="stockos",
    help="StockOS - run real backend services from the terminal.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def status() -> None:
    """Live data-provider health + platform registry readout."""
    commands.status_cmd()


@app.command()
def predict(
    symbol: str = typer.Argument(..., help="EXCHANGE:TICKER or bare ticker, e.g. NSE:RELIANCE"),
    timeframe: str = typer.Option("1W", "--timeframe", "-t", help="1D|1W|1M|3M|6M|1Y|3Y|5Y"),
    option_type: str | None = typer.Option(None, "--option-type", help="CE or PE contract"),
    strike: float | None = typer.Option(None, "--strike", help="Option strike (with --option-type)"),
    expiry: str | None = typer.Option(None, "--expiry", help="Option expiry YYYY-MM-DD"),
) -> None:
    """Predict a price (deterministic engine + LLM agent view)."""
    commands.predict_cmd(symbol, timeframe, option_type, strike, expiry)


@app.command()
def backtest(
    symbol: str = typer.Argument(..., help="EXCHANGE:TICKER or bare ticker, e.g. TCS"),
    strategy: str = typer.Option("moving_average_crossover", "--strategy", "-s"),
    interval: str = typer.Option("1d", "--interval", "-i", help=commands._BACKTEST_INTERVALS),
    period: str = typer.Option("2y", "--period", "-p", help=commands._BACKTEST_PERIODS),
    benchmark: str | None = typer.Option(None, "--benchmark", "-b", help="Benchmark symbol"),
    validate: bool = typer.Option(False, "--validate", help="Add Monte Carlo/bootstrap/walk-forward"),
    params: str | None = typer.Option(None, "--params", help="Strategy params as JSON"),
    capital: float = typer.Option(100_000.0, "--capital", help="Initial capital"),
    intraday: bool = typer.Option(False, "--intraday", help="Intraday cost stack"),
) -> None:
    """Run a bar-level backtest on real candles (fills at next open)."""
    commands.backtest_cmd(symbol, strategy, interval, period, benchmark, validate, params, capital, intraday)


@app.command()
def factors(
    symbols: list[str] = typer.Argument(..., help="One or more EXCHANGE:TICKER symbols"),
    factor: str | None = typer.Option(None, "--factor", "-f", help="Single factor name (default: all)"),
    interval: str = typer.Option("1d", "--interval", "-i"),
    period: str = typer.Option("2y", "--period", "-p"),
    forward_days: int = typer.Option(1, "--forward-days", min=1, max=60),
) -> None:
    """Per-factor rank IC over a real symbol panel."""
    commands.factors_cmd(symbols, factor, interval, period, forward_days)


@app.command()
def desk(
    symbol: str = typer.Argument(..., help="EXCHANGE:TICKER, e.g. NSE:RELIANCE"),
    provider: str = typer.Option("", "--provider", help="ollama|openai|anthropic|google|deepseek|openrouter|azure|openai_compatible"),
    deep_model: str | None = typer.Option(None, "--deep-model"),
    quick_model: str | None = typer.Option(None, "--quick-model"),
    api_key: str | None = typer.Option(None, "--api-key", help="Per-run API key (needed for cloud providers)"),
    base_url: str | None = typer.Option(None, "--base-url"),
    user: str | None = typer.Option(None, "--user", help="Email/id of an existing user to persist the run to trading_runs"),
    trade_date: str | None = typer.Option(None, "--trade-date", help="YYYY-MM-DD (default: today)"),
    max_debate: int | None = typer.Option(None, "--max-debate"),
    max_risk: int | None = typer.Option(None, "--max-risk"),
) -> None:
    """Run the full Trading Desk (LLM multi-agent) analysis."""
    commands.desk_cmd(
        symbol, provider, deep_model, quick_model, api_key, base_url,
        user, trade_date, max_debate, max_risk,
    )


@app.command()
def runs(
    user: str = typer.Argument(..., help="Email/id of the user whose trading runs to list"),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
) -> None:
    """List a user's persisted Trading Desk runs."""
    commands.runs_cmd(user, limit)


def main() -> None:
    app()
