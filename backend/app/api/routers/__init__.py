from fastapi import APIRouter

from app.api.routers import (
    action_center,
    analysis,
    analyzer,
    brokers,
    chart_markup,
    historify,
    auth,
    mcp_client,
    autopilot,
    instruments_new as instruments,
    market,
    master_contract,
    memory,
    orders,
    options,
    options_analytics,
    portfolio,
    predictions,
    quant,
    quantlib,
    research,
    scheduled,
    settings,
    swarm,
    terminal,
    trading,
    watchlist,
)

api_router = APIRouter()
api_router.include_router(action_center.router)
api_router.include_router(analyzer.router)
api_router.include_router(analyzer.compat_router)
api_router.include_router(auth.router)
api_router.include_router(brokers.router)
api_router.include_router(chart_markup.router)
api_router.include_router(historify.router)
api_router.include_router(mcp_client.router)
api_router.include_router(market.router)
api_router.include_router(master_contract.router)
api_router.include_router(instruments.router)
api_router.include_router(watchlist.router)
api_router.include_router(portfolio.router)
api_router.include_router(options.router)
api_router.include_router(options_analytics.analytics_router)
api_router.include_router(options_analytics.margin_router)
api_router.include_router(research.router)
api_router.include_router(analysis.router)
api_router.include_router(trading.router)
api_router.include_router(quant.router)
api_router.include_router(memory.router)
api_router.include_router(scheduled.router)
api_router.include_router(swarm.router)
api_router.include_router(quantlib.router)
api_router.include_router(predictions.router)
api_router.include_router(settings.router)
api_router.include_router(orders.router)
api_router.include_router(terminal.router)
api_router.include_router(autopilot.router)

__all__ = ["api_router"]