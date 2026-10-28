"""Advanced analysis API routes."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Dict, Optional, Any, AsyncIterator
from datetime import datetime
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import DeepAnalysisRequest
from app.db.models import PredictionHistory
from app.db.session import get_session
from ...services.prediction.engine import PredictionEngine, Timeframe
from ...services.options.engine import OptionsEngine, StrategyType
from ...services.scanners.engine import MarketScanner, ScannerType
from ...services.technical.indicators import TechnicalIndicators
from ...services.news.service import NewsService
from ...services.backtesting.engine import BacktestingEngine
from ...services.data.service import MarketDataService, market_data
from ...services.agents.chart_markup import chart_markup_service
from ...services.data.providers.base import OptionsUnavailableError
from ...services.analysis.sectors import sector_analysis_service
from ...services.options.signals import options_signals_service
from ...services.data.ohlcv import to_dataframe
from ...services.backtesting.costs import india_cost_config
from ...services.backtesting.engine_v2 import BacktestRequest, run_backtest_with_benchmark
from ...services.backtesting.sandbox import StrategySandboxError
from ...services.backtesting.strategies import list_strategies
from ...services.backtesting.portfolio_engine import list_methods as list_optimizers

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Initialize services (wired to the real market data facade so predictions,
# option chains, and scanners use live prices — never fabricated defaults).
prediction_engine = PredictionEngine(market_service=market_data)
options_engine = OptionsEngine(market_service=market_data)
market_scanner = MarketScanner(market_service=market_data)
news_service = NewsService()
backtest_engine = BacktestingEngine()

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


def _parse_timeframe(timeframe: str) -> Timeframe:
    key = _TIME_FRAME_MAP.get((timeframe or "").upper())
    if key is None:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid timeframe '{timeframe}'. Use one of {list(_TIME_FRAME_MAP)}",
        )
    return Timeframe[key]


@router.post("/predict/{symbol}")
async def predict_price(
    symbol: str,
    timeframe: str = "1W",
    option_type: Optional[str] = Query(None),
    strike: Optional[float] = Query(None),
    expiry: Optional[str] = Query(None),
    provider: Optional[str] = Query(None, description="Data provider override (yahoo|tradingview|nse)"),
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Generate AI price prediction.

    The deterministic quantitative engine always runs. When the LLM Stock
    Analysis agent is reachable, its "AI Pro" view is appended on top — both
    methods are used and shown together. Optional ``option_type``/``strike``/
    ``expiry`` predict a specific CE/PE contract (its premium) alongside the
    underlying index; ``provider`` lets the UI pick the data source. Every
    successful run is persisted to the user's prediction history.
    """
    tf = _parse_timeframe(timeframe)
    option = None
    if option_type or strike is not None:
        option = {
            "type": option_type or "CE",
            "strike": strike,
            "expiry": expiry,
        }
    try:
        result = await prediction_engine.predict(
            symbol, tf, use_agent=True, option=option
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    payload = {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "current_price": result.current_price,
        "predicted_price": result.predicted_price,
        "confidence": result.confidence,
        "expected_return": result.expected_return,
        "bear_case": result.bear_case,
        "base_case": result.base_case,
        "bull_case": result.bull_case,
        "reasoning": result.reasoning,
        "factors": result.factors,
        "action": result.action,
        "horizon": result.horizon,
        "trading_stats": result.trading_stats,
    }
    try:
        session.add(
            PredictionHistory(
                user_id=current_user.id,
                symbol=result.symbol,
                timeframe=tf.name,
                payload=json.dumps(payload),
            )
        )
        await session.commit()
    except Exception:  # history must never break a prediction
        await session.rollback()
    return payload

@router.get("/sectors")
async def sector_analysis(
    market: str = Query("india", pattern="^(india|us)$"),
    current_user: dict = Depends(get_current_user),
):
    """Sector and cap-class breakdown computed from real live quotes."""
    try:
        return await sector_analysis_service.analyze(market=market)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sector analysis failed: {e}") from e

@router.get("/options/signals/{symbol}")
async def options_signals(
    symbol: str,
    expiry: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Call/put market signals computed from the real option chain."""
    try:
        return await options_signals_service.signals(symbol, expiry=expiry)
    except OptionsUnavailableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Options signals failed: {e}") from e

@router.get("/options/chain/{symbol}")
async def get_option_chain(
    symbol: str,
    expiry: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Get options chain with Greeks."""
    try:
        expiry_date = datetime.fromisoformat(expiry) if expiry else None
        chain = await options_engine.get_option_chain(symbol, expiry_date)
    except OptionsUnavailableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "symbol": chain.symbol,
        "expiry": chain.expiry.isoformat(),
        "expiries": chain.expiries,
        "spot_price": chain.spot_price,
        "calls": chain.calls,
        "puts": chain.puts,
        "max_pain": chain.max_pain,
        "pcr": chain.pcr,
        "iv_rank": chain.iv_rank
    }

async def _option_premium_history(
    symbol: str,
    strike: float,
    expiry: Optional[str],
    option_type: str = "CE",
    interval: str = "1d",
    period: str = "1mo",
) -> dict:
    """Build the historical theoretical premium for a CE/PE contract.

    Shared by the premium-chart endpoint and the option-contract backtest.
    Black-Scholes over the **real underlying candle history** with the **live
    IV/Greeks of the listed leg**. The result is clearly labelled theoretical —
    the free scanner publishes no historical option prices.
    """
    kind = "call" if str(option_type).upper() in {"CE", "CALL"} else "put"
    try:
        chain = await market_data.get_option_chain(symbol, expiry=expiry)
    except OptionsUnavailableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Options chain failed: {e}") from e
    if not chain:
        raise HTTPException(status_code=404, detail=f"No option chain for {symbol}")

    rows = chain.get(kind + "s") or []
    leg = next(
        (r for r in rows if abs(float(r.get("strike") or 0) - float(strike)) < 0.01), None
    )
    if leg is None and rows:
        leg = min(rows, key=lambda r: abs(float(r.get("strike") or 0) - float(strike)))
    if leg is None:
        raise HTTPException(status_code=404, detail=f"No {option_type} leg at strike {strike} for {symbol}")

    iv = float(leg.get("iv") or 0)
    if iv <= 0:
        raise HTTPException(status_code=422, detail="Leg has no IV; cannot price a premium series")
    used_expiry = chain.get("expiry") or expiry
    expiry_date = datetime.fromisoformat(used_expiry[:10])

    try:
        # get_history_auto walks the per-market provider chain (tradingview →
        # yahoo → stooq → local) and returns the first non-empty sanitized
        # result, so an intermittent Yahoo rate-limit can't 404 the premium
        # chart the way a bare get_history (single provider) can.
        history = await market_data.get_history_auto(symbol, interval=interval, period=period)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Underlying history failed: {e}") from e
    candles = (history or {}).get("candles") or []
    if not candles:
        reason = (history or {}).get("error")
        detail = f"No underlying history for {symbol}"
        if reason:
            detail += f" ({reason})"
        raise HTTPException(status_code=404, detail=detail)

    today = datetime.now()
    series = []
    for c in candles:
        ts = c.get("ts") or c.get("timestamp") or c.get("time")
        close = c.get("close")
        if ts is None or close is None:
            continue
        try:
            when = datetime.fromisoformat(str(ts)[:19])
        except ValueError:
            when = today
        days = max((expiry_date - when).days, 1)
        tte = days / 365.0
        premium = options_engine.theoretical_price(
            spot=float(close), strike=float(leg.get("strike") or strike),
            time_to_expiry=tte, volatility=iv,
            option_type=kind if kind == "call" else "put",
        )
        series.append({
            "time": str(ts),
            "spot": round(float(close), 2),
            "premium": round(float(premium), 2),
        })

    return {
        "symbol": chain.get("symbol") or symbol,
        "option_type": kind.upper(),
        "strike": float(leg.get("strike") or strike),
        "expiry": used_expiry,
        "iv": round(iv, 4),
        "delta": round(float(leg.get("delta") or 0), 4),
        "gamma": round(float(leg.get("gamma") or 0), 4),
        "theta": round(float(leg.get("theta") or 0), 4),
        "vega": round(float(leg.get("vega") or 0), 4),
        "spot_price": float(chain.get("spot_price") or 0),
        "series": series,
        "available_strikes": sorted({
            float(r.get("strike"))
            for r in (chain.get("calls") or []) + (chain.get("puts") or [])
            if r.get("strike") is not None
        }),
        "available_expiries": list(chain.get("expiries") or []),
    }


@router.get("/options/premium/{symbol:path}")
async def option_premium_history(
    symbol: str,
    strike: float,
    expiry: Optional[str] = None,
    option_type: str = "CE",
    interval: str = "1d",
    period: str = "1mo",
):
    """Historical theoretical premium for a CE/PE contract.

    Pricing is Black-Scholes over the **real underlying candle history** (from
    the market provider) with the **live IV/delta of the listed leg** (from the
    TradingView chain). The result is clearly labelled a theoretical estimate
    — the free scanner publishes no historical option prices, so this is the
    honest, data-driven way to show a premium chart instead of fabricating one.
    """
    return await _option_premium_history(
        symbol, strike, expiry, option_type, interval, period
    )

@router.post("/options/strategy")
async def analyze_option_strategy(
    symbol: str,
    strategy: str = "iron_condor",
    strikes: Optional[List[float]] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """Analyze option strategy."""
    try:
        strategy_type = StrategyType[strategy.upper()]
        result = await options_engine.analyze_strategy(symbol, strategy_type, strikes)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"Unknown strategy '{strategy}'")
    except OptionsUnavailableError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "name": result.name,
        "legs": result.legs,
        "max_profit": result.max_profit,
        "max_loss": result.max_loss,
        "breakeven": result.breakeven,
        "probability_profit": result.probability_profit,
        "expected_return": result.expected_return,
        "greeks": {
            "delta": result.greeks.delta,
            "gamma": result.greeks.gamma,
            "theta": result.greeks.theta,
            "vega": result.greeks.vega,
            "rho": result.greeks.rho
        }
    }

@router.get("/scan/{scanner_type}")
async def scan_market(
    scanner_type: str,
    market: str = "india",
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """Run market scanner."""
    try:
        # ScannerType values are the canonical lowercase keys the UI sends
        # (e.g. "52_week_high", "breakout"); resolve by value, not enum name.
        scanner = ScannerType((scanner_type or "").lower())
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scanner '{scanner_type}'. Use one of {[t.value for t in ScannerType]}",
        )
    try:
        results = await market_scanner.scan(scanner, market, limit)
        return {
            "scanner": scanner_type,
            "market": market,
            "results": [
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "price": r.price,
                    "change_pct": r.change_pct,
                    "volume": r.volume,
                    "signal_strength": r.signal_strength,
                    "matched_criteria": r.matched_criteria
                }
                for r in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/technical/{symbol:path}")
async def technical_series(symbol: str, interval: str = "1d", period: str = "1mo"):
    """Real technical-indicator series over the symbol's candle history.

    Charts (SMA/EMA/RSI/MACD/Bollinger/Stoch/Supertrend/ADX/CCI/MFI/Williams%R/OBV/SAR/Ichimoku)
    are computed deterministically from the **real** OHLCV served by the market service --
    no fabricated values. Used by the AI Research + Trading Desk + deep analysis surfaces
    to render proper charts and signal markers.
    """
    try:
        history = await market_data.get_history_auto(symbol, interval=interval, period=period)
        candles = (history or {}).get("candles") or []
    except Exception:
        candles = []
    resolved = symbol
    if not candles and ":" not in symbol:
        for candidate in (f"NSE:{symbol}", f"NYSE:{symbol}"):
            try:
                history = await market_data.get_history_auto(candidate, interval=interval, period=period)
            except Exception:
                history = None
            candles = (history or {}).get("candles") or []
            if candles:
                resolved = candidate
                break
    if not candles:
        raise HTTPException(status_code=404, detail=f"No history for {symbol}")

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    vols = [float(c.get("volume") or 0) for c in candles]

    ind = TechnicalIndicators
    macd = ind.macd_series(closes)
    bb = ind.bollinger_series(closes, 20)
    sma20 = ind.sma_series(closes, 20)
    sma50 = ind.sma_series(closes, 50)
    stoch = ind.stoch_series(highs, lows, closes)
    supertrend = ind.supertrend_series(highs, lows, closes)
    dmi = ind.dmi_series(highs, lows, closes)
    return {
        "symbol": resolved,
        "interval": interval,
        "period": period,
        "candles": candles,
        "sma20": sma20,
        "sma50": sma50,
        "ema20": ind.ema_series(closes, 20),
        "rsi": ind.rsi_series(closes, 14),
        "macd": macd["macd"],
        "macd_signal": macd["signal"],
        "macd_hist": macd["histogram"],
        "bb_upper": bb["upper"],
        "bb_middle": bb["middle"],
        "bb_lower": bb["lower"],
        "stoch": stoch,
        "supertrend": supertrend,
        "dmi": dmi,
        "adx": dmi["adx"],
        "plus_di": dmi["plus_di"],
        "minus_di": dmi["minus_di"],
        "cci": ind.cci_series(highs, lows, closes, 20),
        "mfi": ind.mfi_series(highs, lows, closes, vols, 14),
        "williams_r": ind.williams_r_series(highs, lows, closes, 14),
        "obv": ind.obv_series(closes, vols),
        "sar": ind.psar_series(highs, lows),
        "ichimoku": ind.ichimoku_series(highs, lows, closes),
        "atr": TechnicalIndicators.atr(highs, lows, closes, 14),
        "vwap": TechnicalIndicators.vwap(highs, lows, closes, vols),
        "latest": ind.analyze_all({"close": closes, "high": highs, "low": lows, "volume": vols}),
        "signals": ind.signal_markers(
            candles, sma20, sma50,
            ind.rsi_series(closes, 14),
            macd["macd"], macd["signal"],
            stoch["%K"], stoch["%D"],
        )[-80:],
    }

@router.get("/intraday")
async def intraday_board(
    market: str = Query("india", pattern="^(india|us)$"),
    interval: str = Query("1m", pattern="^(1m|5m|15m|1h|1d)$"),
    period: str = Query("5d", pattern="^(5d|1mo|3mo|6mo|1y|2y|5y)$"),
    limit: int = Query(90, ge=1, le=120),
):
    """Batch intraday board for EVERY index and stock in a market.

    Fetches real intraday OHLCV for the whole curated universe in one batched
    pass (``asyncio.gather`` over the data service) and returns per-symbol last /
    day open/high/low / change vs prev close / day volume / sparkline. Symbols
    that fail return an ``error`` field instead of dropping — never fabricated.
    """
    from ...services.analysis.intraday import intraday_board_service

    return await intraday_board_service.board(market, interval, period, limit)


@router.get("/options/coverage")
async def options_coverage(
    market: str = Query("india", pattern="^(india|us)$"),
    limit: int = Query(20, ge=1, le=60),
):
    """Which universe symbols actually have a REAL options chain right now.

    Each symbol is probed live (provider-routed) so the map is honest: symbols
    the free feeds do not cover (e.g. ``NSE:FINNIFTY``, US indices) come back
    ``available: false`` with the provider's reason. Results are cached by the
    market service, so the second call is fast.
    """
    import asyncio

    from ...services.data.universe import by_market

    symbols = by_market(market)[:limit]

    async def probe(info: dict) -> dict:
        sym = info["symbol"]
        try:
            chain = await market_data.get_option_chain(sym)
        except OptionsUnavailableError as exc:
            return {
                "symbol": sym,
                "name": info.get("name"),
                "market": info.get("market"),
                "index": bool(info.get("index")),
                "available": False,
                "provider": None,
                "note": str(exc),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "symbol": sym,
                "name": info.get("name"),
                "market": info.get("market"),
                "index": bool(info.get("index")),
                "available": False,
                "provider": None,
                "note": f"Error: {exc}",
            }
        return {
            "symbol": sym,
            "name": info.get("name"),
            "market": info.get("market"),
            "index": bool(info.get("index")),
            "available": True,
            "provider": chain.get("provider"),
            "note": None,
            "expiries": len(chain.get("expiries") or []),
            "strikes": len(chain.get("calls") or []) + len(chain.get("puts") or []),
        }

    rows = await asyncio.gather(*(probe(s) for s in symbols))
    rows.sort(key=lambda r: (not r["available"], not r["index"], r["symbol"]))
    return {"market": market, "rows": rows, "total": len(rows)}


@router.post("/deep")
async def deep_analysis(
    body: DeepAnalysisRequest,
    current_user: dict = Depends(get_current_user),
):
    """Multi-symbol "Ask AI" deep analysis (streams real-data stages + LLM verdict).

    ``stream: false`` returns a plain JSON payload with the same plan/stages/
    answer shape so tests and non-streaming clients stay simple.
    """
    import json

    from fastapi.responses import StreamingResponse

    from ...services.deep.engine import deep_analysis_engine

    if not body.stream:
        return await deep_analysis_engine.run(body)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in deep_analysis_engine.stream(body):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        except Exception as exc:  # noqa: BLE001
            yield (
                "data: "
                + json.dumps({"type": "error", "data": {"detail": f"Deep analysis failed: {exc}"}}, ensure_ascii=False)
                + "\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/scan/custom")
async def custom_scan(
    criteria: Dict[str, Any],
    market: str = "india",
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """Run custom scanner with user criteria."""
    try:
        results = await market_scanner.custom_scan(criteria, market, limit)
        return {
            "criteria": criteria,
            "market": market,
            "results": [
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "price": r.price,
                    "change_pct": r.change_pct,
                    "signal_strength": r.signal_strength,
                    "matched_criteria": r.matched_criteria
                }
                for r in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/technical/{symbol}")
async def get_technical_indicators(
    symbol: str,
    current_user: dict = Depends(get_current_user)
):
    """Calculate all technical indicators."""
    try:
        # Get price data
        market_service = MarketDataService()
        history = await market_service.get_history(symbol, period="3mo")
        
        prices = {
            'close': [h['close'] for h in history],
            'high': [h['high'] for h in history],
            'low': [h['low'] for h in history],
            'volume': [h.get('volume', 0) for h in history]
        }
        
        # Calculate indicators
        results = TechnicalIndicators.analyze_all(prices)
        
        return {
            "symbol": symbol,
            "indicators": {
                name: {
                    "value": ind.value,
                    "signal": ind.signal,
                    "strength": ind.strength
                }
                for name, ind in results.items()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/news")
async def get_market_news(
    symbols: Optional[List[str]] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """Get market news with sentiment analysis."""
    try:
        async with news_service:
            news = await news_service.fetch_news(symbols)
            return {
                "count": len(news),
                "news": [
                    {
                        "title": item.title,
                        "summary": item.summary,
                        "source": item.source,
                        "url": item.url,
                        "published": item.published.isoformat(),
                        "sentiment": item.sentiment.value,
                        "impact_score": item.impact_score,
                        "symbols": item.symbols
                    }
                    for item in news[:50]  # Limit to 50 items
                ]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class BacktestRequestBody(BaseModel):
    """Backtest v2 request — fills at next open, India cost stack by default."""
    symbol: str
    interval: str = "1d"
    period: str = "2y"
    strategy: str = "moving_average_crossover"
    params: Dict[str, Any] = Field(default_factory=dict)
    initial_capital: float = 100000.0
    benchmark_symbol: Optional[str] = None
    run_validation: bool = False
    custom_code: Optional[str] = None
    intraday: bool = False
    # Option-contract backtest: when set, the strategy runs on the theoretical
    # CE/PE premium series instead of the underlying spot history.
    option_type: Optional[str] = None
    option_strike: Optional[float] = None
    option_expiry: Optional[str] = None


@router.get("/backtest/strategies")
async def backtest_strategies(
    current_user: dict = Depends(get_current_user)
):
    """Available built-in strategies, their params, and portfolio optimizers."""
    return {
        "strategies": list_strategies(),
        "optimizers": list_optimizers(),
        "costs": india_cost_config().as_dict(),
    }


@router.post("/backtest")
async def run_backtest_v2(
    body: BacktestRequestBody,
    current_user: dict = Depends(get_current_user)
):
    """Run a bar-level backtest with real cost modeling and optional robustness
    validation (Monte Carlo, bootstrap, walk-forward). Fills at next open, so
    there is no look-ahead. Strategy may be a built-in preset or custom Python
    validated against an AST allowlist and executed in a sandboxed subprocess.
    When ``option_type`` + ``option_strike`` are set, the strategy runs on the
    theoretical CE/PE premium series for that contract instead of the spot.
    """
    try:
        req = BacktestRequest(
            symbol=body.symbol,
            interval=body.interval,
            period=body.period,
            strategy=body.strategy,
            params=body.params,
            initial_capital=body.initial_capital,
            costs=india_cost_config(intraday=body.intraday),
            benchmark_symbol=body.benchmark_symbol,
            validate=body.run_validation,
            custom_code=body.custom_code,
        )
        contract = None
        if body.option_type and body.option_strike is not None:
            premium = await _option_premium_history(
                body.symbol,
                body.option_strike,
                body.option_expiry,
                body.option_type,
                interval=body.interval,
                period=body.period,
            )
            contract = {
                "symbol": premium["symbol"],
                "option_type": premium["option_type"],
                "strike": premium["strike"],
                "expiry": premium["expiry"],
                "iv": premium["iv"],
                "spot_price": premium["spot_price"],
                "available_strikes": premium.get("available_strikes", []),
                "available_expiries": premium.get("available_expiries", []),
            }
            candles = []
            for pt in premium["series"]:
                p = float(pt["premium"])
                candles.append({
                    "ts": pt["time"],
                    "open": p,
                    "high": p,
                    "low": p,
                    "close": p,
                    "volume": 0,
                })
            history = {"symbol": body.symbol, "interval": body.interval, "candles": candles}
            bench_df = None
        else:
            history = await market_data.get_history_auto(
                body.symbol, interval=body.interval, period=body.period
            )
            bench_df = None
            if body.benchmark_symbol:
                try:
                    bench = await market_data.get_history_auto(
                        body.benchmark_symbol, interval=body.interval, period=body.period
                    )
                    bench_df = to_dataframe(bench)
                    if bench_df is None or bench_df.empty:
                        bench_df = None
                except Exception:
                    bench_df = None  # honest degradation: benchmark omitted, not fabricated
        df = to_dataframe(history)
        if df is None or df.empty:
            raise HTTPException(
                status_code=422,
                detail=f"no history available for {body.symbol} ({history.get('error') or history.get('source') or 'no source'})",
            )
        result = run_backtest_with_benchmark(df, bench_df, req)
        if contract:
            result["option_contract"] = contract
        return result
    except StrategySandboxError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/chart-markup")
async def analysis_chart_markup(
    symbol: str = Query(...),
    interval: str = Query("1d"),
    period: str = Query("3mo"),
    provider: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
) -> dict:
    return await chart_markup_service.build(symbol, interval=interval, period=period, provider=provider)
