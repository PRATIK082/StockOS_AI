"""Transaction cost models for backtesting.

Default model follows the India (NSE/BSE) equity stack — broker commission,
slippage, STT, stamp duty, exchange transaction charge, SEBI fee and GST — but
every component is configurable so the same engine prices any market. Costs are
always computed from fill value (Vibe-Trading style), never flat guesses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostConfig:
    """Per-side cost percentages (each expressed as a decimal fraction).

    ``gst_pct`` is applied to (commission + exchange + sebi) only, mirroring
    Indian GST treatment of brokerage/exchange/SEBI charges.
    """

    commission_pct: float = 0.001   # broker charge on turnover
    slippage_pct: float = 0.0005    # execution slippage
    stt_pct: float = 0.001          # securities transaction tax (sell side, delivery)
    stamp_duty_pct: float = 0.00015 # stamp duty (buy side)
    exchange_pct: float = 0.00003   # exchange transaction charge
    sebi_pct: float = 0.000001      # SEBI regulatory fee
    gst_pct: float = 0.18           # GST on (commission+exchange+sebi)

    def buy_cost_pct(self) -> float:
        base = self.commission_pct + self.exchange_pct + self.sebi_pct
        return self.commission_pct + self.slippage_pct + base * (1 + self.gst_pct) + self.stamp_duty_pct

    def sell_cost_pct(self) -> float:
        base = self.commission_pct + self.exchange_pct + self.sebi_pct
        return self.commission_pct + self.slippage_pct + base * (1 + self.gst_pct) + self.stt_pct

    def round_trip_cost_pct(self) -> float:
        return self.buy_cost_pct() + self.sell_cost_pct()

    def as_dict(self) -> dict:
        return {
            "commission_pct": self.commission_pct,
            "slippage_pct": self.slippage_pct,
            "stt_pct": self.stt_pct,
            "stamp_duty_pct": self.stamp_duty_pct,
            "exchange_pct": self.exchange_pct,
            "sebi_pct": self.sebi_pct,
            "gst_pct": self.gst_pct,
            "buy_cost_pct": round(self.buy_cost_pct(), 6),
            "sell_cost_pct": round(self.sell_cost_pct(), 6),
            "round_trip_cost_pct": round(self.round_trip_cost_pct(), 6),
        }


def india_cost_config(*, intraday: bool = False) -> CostConfig:
    """A realistic default for NSE/BSE equity.

    Delivery: STT 0.1% (sell), stamp 0.015% (buy). Intraday: STT 0.025% (sell),
    no stamp duty on buy.
    """
    if intraday:
        return CostConfig(stt_pct=0.00025, stamp_duty_pct=0.0)
    return CostConfig()
