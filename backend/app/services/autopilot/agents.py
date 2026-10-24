"""Agent squad for the Autopilot supervisor.

Seven small, deterministic agents. Each returns a plain dict of evidence so the
engine can persist it verbatim into ``autopilot_run_nodes`` and the debrief
agent can compose the report from it. The only side effects in the whole squad
are the ``execute`` agent (paper broker orders + tracked option positions) and
the ``selfreview`` agent (trade journal + memories) — research agents never
touch the broker.

Design notes
------------
- Everything is deterministic and testable: no LLM call by default
  (``use_llm`` on the config reserves the Slice-6 opt-in debrief).
- All market access goes through the real ``market_data`` facade — never
  fabricated quotes.
- Proposals are *gated*: the ``riskgate`` agent runs every one through
  RiskEngine + live broker state, and the paper broker's own guards (daily
  loss, max positions, duplicate-order-per-day) still apply at execution.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.logging import get_logger
from app.services.data.ohlcv import sanitize_history, to_dataframe
from app.services.data.service import market_data
from app.services.memory.store import memory_store
from app.services.options.signals import OptionsSignalsService

logger = get_logger("autopilot.agents")


# ------------------------------------------------------------------------- #
# Shared types
# ------------------------------------------------------------------------- #


@dataclass
class Proposal:
    """A broker-bound action proposed by research/monitor agents."""

    symbol: str
    side: str  # BUY | SELL
    action: str  # entry | take_profit | stop_loss | trail_stop
    reason: str
    qty: int = 1
    price_ref: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "action": self.action,
            "reason": self.reason,
            "qty": self.qty,
            "price_ref": self.price_ref,
            "detail": self.detail,
        }


def _num(value: Any) -> float | None:
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


async def live_price(symbol: str, fallback: float = 0.0) -> float:
    """Best-effort live price from the real quote facade."""
    try:
        quote = await market_data.get_quote(symbol)
        price = _num(quote.get("price") or quote.get("last_price") or fallback)
        return price if price and price > 0 else fallback
    except Exception:  # noqa: BLE001
        return fallback


def _technical_quick(history: dict) -> dict:
    """Small deterministic scoring of a real candle series (30+ bars)."""
    from app.services.technical.indicators import TechnicalIndicators as TI

    candles = (history or {}).get("candles") or []
    if len(candles) < 30:
        return {"direction": "NEUTRAL", "strength": 0.0, "reasons": ["insufficient history (<30 bars)"]}
    df = to_dataframe(sanitize_history(history))
    close = df["close"].tolist()
    rsi = float(TI.rsi(close))
    sma20 = float(TI.sma(close, 20))
    sma50 = float(TI.sma(close, 50))
    last = close[-1]
    mom = last / close[-20] - 1 if len(close) >= 20 else 0.0
    signals: list[str] = []
    strength = 0.0
    direction = "NEUTRAL"
    if rsi < 70 and sma20 > sma50 and mom > 0.02:
        direction = "LONG"
        strength = min(0.9, abs(mom) * 6 + (1 - abs(rsi - 55) / 55) * 0.4)
        signals.append(f"RSI {rsi:.1f}")
        signals.append("SMA20>50")
        signals.append(f"1M move +{mom*100:.1f}%")
    elif rsi > 30 and sma20 < sma50 and mom < -0.02:
        direction = "SHORT"
        strength = min(0.9, abs(mom) * 6 + (1 - abs(rsi - 45) / 45) * 0.4)
        signals.append(f"RSI {rsi:.1f}")
        signals.append("SMA20<50")
        signals.append(f"1M move {mom*100:.1f}%")
    else:
        signals.append(f"range (RSI {rsi:.1f})")
    return {"direction": direction, "strength": round(strength, 3), "reasons": signals, "rsi": rsi}


# ------------------------------------------------------------------------- #
# sentinel — protect open positions (profit-taking / stop-loss / trailing)
# ------------------------------------------------------------------------- #


async def sentinel_agent(user_id: str, config: Any) -> dict[str, Any]:
    from app.brokers.paper import PaperBroker

    broker = PaperBroker(user_id=user_id)
    positions = await broker.positions()
    monitored: list[dict[str, Any]] = []
    proposals: list[Proposal] = []

    for pos in positions:
        qty = _num(pos.quantity)
        avg = _num(pos.average_price)
        if not qty or qty <= 0 or not avg or avg <= 0:
            continue
        last = await live_price(pos.symbol, fallback=avg)
        pnl_pct = (last / avg - 1) * 100 if avg else 0.0

        # Trailing floor persisted across cycles (per symbol, per user).
        trail_key = f"autopilot:trail:{pos.symbol}"
        mem = await memory_store.get(user_id, trail_key)
        try:
            peak = float(mem["value"].get("peak_pct", pnl_pct)) if mem else pnl_pct
        except (TypeError, ValueError):
            peak = pnl_pct
        peak = max(peak, pnl_pct)
        await memory_store.set(
            user_id, trail_key, {"peak_pct": peak, "symbol": pos.symbol, "updated_at": date.today().isoformat()},
            kind="autopilot",
            scope="trail",
        )

        action, reason = "HOLD", "within plan"
        if pnl_pct <= config.stop_loss_pct:
            action, reason = "SELL", "stop_loss"
        elif pnl_pct >= config.take_profit_pct:
            action, reason = "SELL", "take_profit"
        elif config.trail_enabled and pnl_pct > 0 and (peak - pnl_pct) >= config.trail_drop_pct:
            action, reason = "SELL", "trail_stop"

        row: dict[str, Any] = {
            "symbol": pos.symbol,
            "quantity": qty,
            "average_price": avg,
            "last_price": last,
            "pnl_pct": round(pnl_pct, 2),
            "peak_pnl_pct": round(peak, 2),
            "action": action,
            "reason": reason,
        }
        monitored.append(row)
        if action == "SELL":
            proposals.append(
                Proposal(
                    symbol=pos.symbol,
                    side="SELL",
                    action=reason,
                    reason=f"{reason}: pnl {pnl_pct:.2f}% (stop {config.stop_loss_pct}%, target {config.take_profit_pct}%)",
                    qty=int(qty),
                    price_ref=last,
                    detail=row,
                )
            )

    return {
        "agent": "sentinel",
        "n_positions": len(positions),
        "monitored": monitored,
        "proposals": [p.as_dict() for p in proposals],
    }


# ------------------------------------------------------------------------- #
# signal — fused multi-scanner idea generation
# ------------------------------------------------------------------------- #


async def signal_agent(config: Any, limit: int = 8) -> dict[str, Any]:
    from app.services.scanners.engine import MarketScanner, ScannerType

    scanner = MarketScanner(market_service=market_data, universe={})
    hits: dict[str, list[dict[str, Any]]] = {}
    for scanner_name in config.scanners:
        try:
            results = await scanner.scan(ScannerType(scanner_name), config.market, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("scanner %s failed: %s", scanner_name, exc)
            continue
        for r in results:
            hits.setdefault(r.symbol, []).append(
                {"scanner": scanner_name, "strength": r.signal_strength, "criteria": r.matched_criteria[:3]}
            )

    # Fold in watchlist symbols so they are always researched.
    for symbol in config.watchlist:
        hits.setdefault(symbol, [{"scanner": "watchlist", "strength": 0.0, "criteria": ["user watchlist"]}])

    scored: list[dict[str, Any]] = []
    for symbol, rows in hits.items():
        merged_strength = sum(r["strength"] for r in rows) / float(len(rows) or 1)
        reasons = sorted({c for r in rows for c in r["criteria"]})
        scored.append({"symbol": symbol, "strength": round(merged_strength, 3), "scanners": [r["scanner"] for r in rows], "reasons": reasons[:4]})

    scored.sort(key=lambda s: s["strength"], reverse=True)
    top = scored[: max(limit, config.max_new_entries * 3)]

    candidates: list[dict[str, Any]] = []
    for row in top:
        try:
            history = await market_data.get_history_auto(row["symbol"], interval="1d", period="3mo")
        except Exception:  # noqa: BLE001
            history = {}
        tech = _technical_quick(history)
        candidates.append({**row, **tech})

    return {
        "agent": "signal",
        "market": config.market,
        "scanners": config.scanners,
        "candidates": candidates,
    }


# ------------------------------------------------------------------------- #
# optionstrategy — turn chain bias into concrete CE/PE plays (paper-tracked)
# ------------------------------------------------------------------------- #


async def optionstrategy_agent(config: Any, candidate_symbols: list[str]) -> dict[str, Any]:
    svc = OptionsSignalsService(market_service=market_data)
    symbols = list(dict.fromkeys([*candidate_symbols, *config.watchlist]))
    plays: list[dict[str, Any]] = []
    skipped: list[str] = []
    for symbol in symbols:
        if len(plays) >= config.option_max_plays:
            break
        try:
            signals = await svc.signals(symbol)
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{symbol} (no chain: {exc})")
            continue
        bias = signals.get("bias")
        if bias not in ("CALL", "PUT"):
            skipped.append(f"{symbol} (neutral bias)")
            continue
        try:
            chain = await market_data.get_option_chain(symbol)
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{symbol} (chain error: {exc})")
            continue
        strike, premium = _pick_leg(chain, "CE" if bias == "CALL" else "PE")
        if not strike:
            skipped.append(f"{symbol} (no leg for {bias})")
            continue
        expiry = signals.get("expiry") or (chain.get("expiries") or [None])[0]
        plays.append(
            {
                "symbol": symbol,
                "option_type": "CE" if bias == "CALL" else "PE",
                "strike": strike,
                "expiry": expiry,
                "bias": bias,
                "strategy": signals.get("strategy"),
                "iv_skew": signals.get("iv_skew"),
                "max_pain": signals.get("max_pain"),
                "premium": premium,
                "lots": config.option_lots,
                "reason": (signals.get("recommendation") or signals.get("strategy") or "")[:300],
            }
        )
    return {"agent": "optionstrategy", "plays": plays, "skipped": skipped}


# ------------------------------------------------------------------------- #
# riskgate — run every proposal through RiskEngine + live broker state
# ------------------------------------------------------------------------- #


async def riskgate_agent(
    user_id: str,
    config: Any,
    proposals: list[Proposal],
) -> dict[str, Any]:
    from app.brokers.paper import PaperBroker
    from app.core.config import get_settings
    from app.services.risk.risk_engine import RiskEngine

    broker = PaperBroker(user_id=user_id)
    settings = get_settings()
    open_positions = {p.symbol: float(p.quantity) for p in await broker.positions()}
    gated: list[dict[str, Any]] = []

    for p in proposals:
        entry: dict[str, Any] = p.as_dict()
        if p.side == "SELL":
            held = open_positions.get(p.symbol, 0.0)
            entry["qty"] = int(held)
            entry["allowed"] = held > 0
            if not entry["allowed"]:
                entry["reason"] = f"no open position in {p.symbol}"
            else:
                entry["reason"] = p.reason
            gated.append(entry)
            continue

        # New long entry: size by the risk engine, capped by config.entry_qty.
        try:
            quote = await broker.quote(p.symbol)
            entry_price = Decimal(str(quote.last_price))
        except Exception as exc:  # noqa: BLE001
            entry["allowed"] = False
            entry["reason"] = f"no quote for sizing: {exc}"
            gated.append(entry)
            continue
        if not entry_price or entry_price <= 0:
            entry["allowed"] = False
            entry["reason"] = "no valid quote for sizing"
            gated.append(entry)
            continue

        stop = entry_price * (Decimal("1") + (Decimal(str(config.stop_loss_pct)) / Decimal("100")))
        sizing = RiskEngine.calculate_position_size(
            Decimal(str(settings.max_order_risk_rupees)),
            entry_price,
            stop,
        )
        qty_cap = int(sizing["quantity"])
        qty = min(max(int(config.entry_qty), 0), max(qty_cap, 0))
        if qty <= 0:
            entry["allowed"] = False
            entry["reason"] = f"risk sizing yields zero quantity ({sizing.get('reason') or 'cap reached'})"
            gated.append(entry)
            continue

        ok, reason = RiskEngine.check_order(
            symbol=p.symbol,
            side="BUY",
            quantity=Decimal(qty),
            entry_price=entry_price,
            stop_loss_price=stop,
        )
        entry["qty"] = qty
        entry["price_ref"] = float(entry_price)
        entry["allowed"] = bool(ok)
        entry["reason"] = p.reason if ok else (reason or "risk check failed")
        gated.append(entry)

    return {
        "agent": "riskgate",
        "approved": [g for g in gated if g["allowed"]],
        "rejected": [g for g in gated if not g["allowed"]],
    }


# ------------------------------------------------------------------------- #
# execute — the only agent with real side effects (paper broker + tracked legs)
# ------------------------------------------------------------------------- #


async def execute_agent(
    user_id: str,
    gated_proposals: list[dict[str, Any]],
    option_plays: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from app.brokers.interface import BrokerSide, OrderType, ProductType
    from app.brokers.paper import PaperBroker
    from app.db.models import OptionPosition
    from app.db.session import SessionFactory

    broker = PaperBroker(user_id=user_id)
    fills: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []

    for p in gated_proposals:
        if not p["allowed"]:
            continue
        try:
            result = await broker.place_order(
                symbol=p["symbol"],
                side=BrokerSide(p["side"]),
                product=ProductType.CNC,
                order_type=OrderType.MARKET,
                quantity=Decimal(str(p["qty"])),
            )
        except Exception as exc:  # noqa: BLE001  (broker raises on hard errors)
            rejects.append({**p, "error": str(exc)})
            continue
        if result.status in ("rejected", "cancelled"):
            rejects.append({**p, "error": result.error_message or "execution rejected"})
            continue
        fill = {
            "symbol": p["symbol"],
            "side": p["side"],
            "action": p["action"],
            "qty": p["qty"],
            "fill_price": float(result.filled_price) if result.filled_price else None,
            "order_id": result.order_id,
            "pnl": float(result.pnl) if result.pnl else None,
            "reason": p.get("reason", ""),
        }
        fills.append(fill)
        executions.append(fill)
        # Mirror the manual /v1/orders/submit behaviour so terminal analytics
        # and the order history page see autopilot fills too.
        await _persist_order_record(user_id, p, result)

    tracked: list[dict[str, Any]] = []
    for play in option_plays or []:
        try:
            expiry = _parse_expiry(play.get("expiry"))
            row = OptionPosition(
                user_id=user_id,
                symbol=play["symbol"],
                option_type=play["option_type"],
                strike=str(play["strike"]),
                expiry=expiry,
                quantity=str(play.get("lots", 1)),
                premium=str(play.get("premium") or 0),
            )
            async with SessionFactory() as session:
                session.add(row)
                await session.commit()
            tracked.append(
                {
                    "symbol": play["symbol"],
                    "option_type": play["option_type"],
                    "strike": play["strike"],
                    "expiry": play.get("expiry"),
                    "lots": play.get("lots", 1),
                }
            )
        except Exception as exc:  # noqa: BLE001
            rejects.append({"symbol": play.get("symbol"), "action": "option_track", "error": str(exc)})

    return {
        "agent": "execute",
        "fills": fills,
        "rejects": rejects,
        "executions": executions,
        "option_tracks": tracked,
    }


async def _persist_order_record(user_id: str, p: dict[str, Any], result: Any) -> None:
    from app.db.models import Order as OrderModel
    from app.db.session import SessionFactory

    try:
        from sqlalchemy import insert

        async with SessionFactory() as session:
            await session.execute(
                insert(OrderModel).values(
                    user_id=user_id,
                    symbol=p["symbol"],
                    side=p["side"],
                    quantity=str(p["qty"]),
                    price=float(result.filled_price or 0),
                    status="filled",
                    order_type="MARKET",
                    extra_data=f"autopilot:{p.get('action', 'entry')}",
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist autopilot order record for %s: %s", p.get("symbol"), exc)


def _parse_expiry(value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        import datetime

        return datetime.date.today() + datetime.timedelta(days=30)


# ------------------------------------------------------------------------- #
# selfreview — the self agent mode: score the mission and keep a journal
# ------------------------------------------------------------------------- #


async def selfreview_agent(
    user_id: str,
    mission: str,
    *,
    sentinel_evidence: dict[str, Any],
    fills: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    option_tracks: list[dict[str, Any]],
) -> dict[str, Any]:
    n_fills = len(fills)
    n_rejects = len(rejects)
    n_monitored = len(sentinel_evidence.get("monitored", []))
    n_proposals = len(sentinel_evidence.get("proposals", []))

    realised = sum((fill.get("pnl") or 0.0) for fill in fills)
    exits = [f for f in fills if f["side"] == "SELL"]
    entries = [f for f in fills if f["side"] == "BUY"]

    halted = any("daily loss" in (r.get("error") or "").lower() for r in rejects)
    if not halted and n_monitored and sum(1 for m in sentinel_evidence.get("monitored", []) if m.get("action") == "SELL") == n_monitored:
        halted = True  # whole book stopped out

    discipline = 1.0
    if n_rejects:
        discipline = max(0.2, 1.0 - n_rejects / max(1, n_rejects + n_fills))
    score = round(discipline, 3)

    notes = [
        f"monitored {n_monitored} position(s), {n_proposals} exit proposal(s)",
        f"{n_fills} fill(s) ({len(entries)} entry / {len(exits)} exit), {n_rejects} rejection(s)",
        f"realised mission P&L ≈ {realised:+.2f}",
    ]
    review = {
        "agent": "selfreview",
        "mission": mission,
        "n_fills": n_fills,
        "n_rejects": n_rejects,
        "n_entries": len(entries),
        "n_exits": len(exits),
        "n_option_tracks": len(option_tracks),
        "realised_pnl": round(realised, 2),
        "score": score,
        "halt_recommended": halted,
        "notes": notes,
    }

    await _write_journal(user_id, review)
    await memory_store.set(
        user_id,
        "autopilot:self_review",
        review,
        kind="autopilot",
        scope="review",
    )
    return review


async def _write_journal(user_id: str, review: dict[str, Any]) -> None:
    import hashlib

    outcome = "flat"
    if review["realised_pnl"] > 0:
        outcome = "win"
    elif review["realised_pnl"] < 0:
        outcome = "loss"
    rationale = " | ".join(review["notes"]) + f" | score {review['score']}"
    key = f"journal:{hashlib.sha1(f'autopilot-mission-{review['mission']}-{date.today().isoformat()}'.encode('utf-8')).hexdigest()[:12]}"
    try:
        await memory_store.set(
            user_id,
            key,
            {
                "symbol": "MISSION",
                "side": "HOLD",
                "rationale": rationale[:4096],
                "pnl": review["realised_pnl"],
                "outcome": outcome,
                "tags": ["autopilot", "self-review", review["mission"]],
            },
            kind="journal",
            scope="autopilot",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("selfreview journal write failed: %s", exc)


# ------------------------------------------------------------------------- #
# debrief — human-readable mission report from all node evidence
# ------------------------------------------------------------------------- #


def debrief_agent(
    *,
    mission: str,
    run_id: str,
    sentinel_evidence: dict[str, Any],
    signal_evidence: dict[str, Any] | None,
    options_evidence: dict[str, Any] | None,
    gate_evidence: dict[str, Any],
    execute_evidence: dict[str, Any],
    review: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append(f"# Agent Autopilot — {mission} run `{run_id[:8]}`")
    lines.append("")

    lines.append("## Sentinel (position protection)")
    lines.append(f"- Monitored **{sentinel_evidence.get('n_positions', 0)}** position(s).")
    for row in sentinel_evidence.get("monitored", []):
        lines.append(
            f"  - `{row['symbol']}` pnl **{row['pnl_pct']:+.2f}%** (peak {row['peak_pnl_pct']:+.2f}%) → **{row['action']}** ({row['reason']})"
        )
    lines.append("")

    if signal_evidence:
        lines.append("## Signal (idea generation)")
        for c in signal_evidence.get("candidates", [])[:6]:
            lines.append(
                f"  - `{c['symbol']}` strength {c['strength']:.2f} → {c.get('direction', 'NEUTRAL')} — {', '.join(c.get('reasons', [])[:3])}"
            )
        lines.append("")

    if options_evidence:
        lines.append("## Option strategy (F&O plays)")
        for play in options_evidence.get("plays", []):
            lines.append(
                f"  - `{play['symbol']}` {play['option_type']} @ {play['strike']} ({play.get('expiry')}) bias {play['bias']} — {play.get('reason', '')[:160]}"
            )
        if options_evidence.get("skipped"):
            lines.append(f"  - skipped: {len(options_evidence['skipped'])}")
        lines.append("")

    lines.append("## Risk gate")
    lines.append(f"- Approved **{len(gate_evidence.get('approved', []))}**, rejected **{len(gate_evidence.get('rejected', []))}**.")
    lines.append("")

    lines.append("## Execution")
    for f in execute_evidence.get("fills", []):
        lines.append(f"  - {f['side']} `{f['symbol']}` qty {f['qty']} @ {f.get('fill_price')} ({f['action']})")
    for r in execute_evidence.get("rejects", []):
        lines.append(f"  - rejected `{r.get('symbol')}` — {r.get('error', r.get('reason'))}")
    for t in execute_evidence.get("option_tracks", []):
        lines.append(f"  - tracked option {t['option_type']} `{t['symbol']}` @ {t['strike']} x{t.get('lots', 1)} (paper)")
    lines.append("")

    lines.append("## Self review")
    lines.append(f"- Score **{review.get('score')}**, mission P&L **{review.get('realised_pnl', 0):+.2f}**.")
    for note in review.get("notes", []):
        lines.append(f"  - {note}")
    lines.append(f"- Halt recommended: **{review.get('halt_recommended', False)}**")
    lines.append("")
    lines.append("> Everything above is derived from real StockOS data and executed in paper mode unless the account mode says otherwise.")
    return "\n".join(lines)


def _pick_leg(chain: dict, option_type: str) -> tuple[float | None, float | None]:
    """Nearest-to-spot strike on the requested side with its listed premium."""
    spot = _num(chain.get("spot_price"))
    rows = [r for r in chain.get(("calls" if option_type == "CE" else "puts"), []) if _num(r.get("strike"))]
    if not rows:
        return None, None
    if spot is not None:
        leg = min(rows, key=lambda r: abs(_num(r.get("strike")) - spot))
    else:
        leg = sorted(rows, key=lambda r: _num(r.get("strike")))[len(rows) // 2]
    return _num(leg.get("strike")), _num(leg.get("last") or leg.get("premium"))