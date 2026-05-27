"""
Smart Order Execution — TWAP / VWAP algorithms.

Why algorithmic execution matters:
- A market order for 10,000 shares in a thin stock can move price 0.5-1%
  before you're filled → massive slippage kills edge
- TWAP: spreads order evenly over time → predictable, simple
- VWAP: concentrates orders during high-volume periods → follows liquidity
- Participation Rate: never exceed X% of market volume → stay hidden

TWAP (Time-Weighted Average Price):
    split total_qty into N equal slices, execute one slice every T minutes
    best for: liquid stocks, time-insensitive execution, steady flow

VWAP (Volume-Weighted Average Price):
    weight each slice by expected volume distribution (U-shaped intraday)
    more aggressive in 9:15-10:00 AM and 2:30-3:30 PM (high volume periods)
    best for: benchmark-tracking, institutional-style execution

Participation Rate:
    each slice ≤ max_participation_pct of actual market volume for that interval
    guarantees you never move the market → safest for large orders

Indian market volume profile (approximate):
    - 9:15-10:00: ~25% of daily volume
    - 10:00-12:00: ~25%
    - 12:00-14:00: ~15%
    - 14:00-15:30: ~35%
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger("smart_order")


# ── Volume profile for NSE (time → % of daily volume) ────────────────────────

# Half-hourly volume weights (9:15-15:30 = 13 half-hour slots)
NSE_VOLUME_PROFILE = {
    "09:15": 0.120,   # opening auction + first 15 min
    "09:30": 0.080,
    "10:00": 0.065,
    "10:30": 0.055,
    "11:00": 0.050,
    "11:30": 0.048,
    "12:00": 0.045,
    "12:30": 0.042,
    "13:00": 0.040,
    "13:30": 0.042,
    "14:00": 0.055,
    "14:30": 0.070,
    "15:00": 0.088,
    "15:15": 0.100,   # closing auction
}


@dataclass
class OrderSlice:
    slice_number:   int
    scheduled_time: datetime
    target_qty:     int
    executed_qty:   int   = 0
    executed_price: float = 0.0
    status:         str   = "PENDING"   # PENDING | EXECUTED | SKIPPED | PARTIAL


@dataclass
class AlgoOrderResult:
    algo_type:      str
    symbol:         str
    total_qty:      int
    executed_qty:   int
    avg_price:      float
    benchmark_price: float   # TWAP or VWAP benchmark
    slippage_bps:   float   # (avg_price - benchmark) / benchmark * 10000
    slices:         List[OrderSlice] = field(default_factory=list)
    start_time:     Optional[datetime] = None
    end_time:       Optional[datetime] = None

    @property
    def fill_rate(self) -> float:
        return self.executed_qty / self.total_qty if self.total_qty > 0 else 0.0

    @property
    def completion_pct(self) -> float:
        return self.fill_rate * 100.0


class TWAPOrder:
    """
    Time-Weighted Average Price execution.
    Splits order into equal time slices over execution window.
    """

    def __init__(
        self,
        symbol:        str,
        total_qty:     int,
        direction:     str,         # "BUY" or "SELL"
        start_time:    datetime,
        end_time:      datetime,
        n_slices:      int   = 10,
        randomise:     bool  = True,   # ±10% qty randomisation to avoid detection
        min_qty:       int   = 1,
    ):
        self.symbol     = symbol
        self.total_qty  = total_qty
        self.direction  = direction
        self.start_time = start_time
        self.end_time   = end_time
        self.n_slices   = n_slices
        self.randomise  = randomise
        self.min_qty    = min_qty
        self._slices:   List[OrderSlice] = []
        self._built     = False

    def build_schedule(self) -> List[OrderSlice]:
        """Compute the time schedule for all slices."""
        duration  = (self.end_time - self.start_time).total_seconds()
        interval  = duration / self.n_slices
        base_qty  = self.total_qty // self.n_slices
        remainder = self.total_qty % self.n_slices

        rng = np.random.RandomState(42)
        slices = []
        for i in range(self.n_slices):
            t = self.start_time + timedelta(seconds=i * interval)
            qty = base_qty + (1 if i < remainder else 0)

            if self.randomise and qty > 1:
                noise = int(qty * 0.10 * rng.randn())
                qty   = max(self.min_qty, qty + noise)

            slices.append(OrderSlice(
                slice_number=i + 1,
                scheduled_time=t,
                target_qty=qty,
            ))

        self._slices = slices
        self._built  = True
        logger.info(
            f"TWAP schedule: {self.symbol} {self.direction} "
            f"qty={self.total_qty} in {self.n_slices} slices "
            f"({self.start_time.strftime('%H:%M')}→{self.end_time.strftime('%H:%M')})"
        )
        return slices

    def next_slice(self, current_time: Optional[datetime] = None) -> Optional[OrderSlice]:
        """Return the next pending slice to execute."""
        if not self._built:
            self.build_schedule()
        now = current_time or datetime.now()
        for sl in self._slices:
            if sl.status == "PENDING" and sl.scheduled_time <= now:
                return sl
        return None

    def mark_executed(
        self,
        slice_number: int,
        executed_qty: int,
        executed_price: float,
    ) -> None:
        for sl in self._slices:
            if sl.slice_number == slice_number:
                sl.executed_qty   = executed_qty
                sl.executed_price = executed_price
                sl.status = "EXECUTED" if executed_qty >= sl.target_qty else "PARTIAL"
                break

    def result(self) -> AlgoOrderResult:
        executed = [s for s in self._slices if s.status in ("EXECUTED", "PARTIAL")]
        total_executed = sum(s.executed_qty for s in executed)
        avg_price = (
            sum(s.executed_qty * s.executed_price for s in executed) / total_executed
            if total_executed > 0 else 0.0
        )
        twap_price = (
            sum(s.executed_price for s in executed) / len(executed)
            if executed else 0.0
        )
        slippage_bps = ((avg_price - twap_price) / twap_price * 10000
                        if twap_price > 0 else 0.0)
        return AlgoOrderResult(
            algo_type="TWAP", symbol=self.symbol,
            total_qty=self.total_qty, executed_qty=total_executed,
            avg_price=round(avg_price, 2), benchmark_price=round(twap_price, 2),
            slippage_bps=round(slippage_bps, 2), slices=self._slices,
            start_time=self.start_time, end_time=self.end_time,
        )


class VWAPOrder:
    """
    Volume-Weighted Average Price execution.
    Sizes each slice proportional to expected volume in that time bucket.
    """

    def __init__(
        self,
        symbol:             str,
        total_qty:          int,
        direction:          str,
        start_time:         datetime,
        end_time:           datetime,
        volume_profile:     Optional[dict] = None,
        max_participation:  float = 0.10,    # max 10% of market volume per slice
    ):
        self.symbol             = symbol
        self.total_qty          = total_qty
        self.direction          = direction
        self.start_time         = start_time
        self.end_time           = end_time
        self.volume_profile     = volume_profile or NSE_VOLUME_PROFILE
        self.max_participation  = max_participation
        self._slices:           List[OrderSlice] = []
        self._built             = False

    def build_schedule(self) -> List[OrderSlice]:
        """
        Allocate quantity to each 30-min bucket proportional to volume profile.
        """
        # Get time buckets that fall within start-end window
        buckets = []
        for time_str, weight in self.volume_profile.items():
            h, m    = map(int, time_str.split(":"))
            bucket_dt = self.start_time.replace(hour=h, minute=m, second=0)
            if self.start_time <= bucket_dt <= self.end_time:
                buckets.append((bucket_dt, weight))

        if not buckets:
            # Fallback: equal distribution across 10 slices
            logger.warning("VWAP: no profile buckets in window, falling back to TWAP")
            twap = TWAPOrder(self.symbol, self.total_qty, self.direction,
                             self.start_time, self.end_time)
            self._slices = twap.build_schedule()
            self._built = True
            return self._slices

        total_weight = sum(w for _, w in buckets)
        slices = []
        for i, (bucket_dt, weight) in enumerate(buckets):
            qty = max(1, int(self.total_qty * weight / total_weight))
            slices.append(OrderSlice(
                slice_number=i + 1,
                scheduled_time=bucket_dt,
                target_qty=qty,
            ))

        # Fix rounding: add remainder to highest-volume bucket
        total_scheduled = sum(s.target_qty for s in slices)
        if total_scheduled < self.total_qty:
            max_idx = max(range(len(slices)), key=lambda i: slices[i].target_qty)
            slices[max_idx].target_qty += self.total_qty - total_scheduled

        self._slices = slices
        self._built  = True
        logger.info(
            f"VWAP schedule: {self.symbol} {self.direction} "
            f"qty={self.total_qty} in {len(slices)} buckets"
        )
        return slices

    def next_slice(self, current_time: Optional[datetime] = None) -> Optional[OrderSlice]:
        if not self._built:
            self.build_schedule()
        now = current_time or datetime.now()
        for sl in self._slices:
            if sl.status == "PENDING" and sl.scheduled_time <= now:
                return sl
        return None

    def apply_participation_limit(
        self,
        slice_: OrderSlice,
        market_volume_in_period: int,
    ) -> int:
        """Cap slice quantity to max_participation % of market volume."""
        max_qty = int(market_volume_in_period * self.max_participation)
        return min(slice_.target_qty, max(1, max_qty))

    def result(self) -> AlgoOrderResult:
        executed = [s for s in self._slices if s.status in ("EXECUTED", "PARTIAL")]
        total_executed = sum(s.executed_qty for s in executed)
        avg_price = (
            sum(s.executed_qty * s.executed_price for s in executed) / total_executed
            if total_executed > 0 else 0.0
        )
        vwap_price = avg_price   # benchmark is our own VWAP
        slippage_bps = 0.0
        return AlgoOrderResult(
            algo_type="VWAP", symbol=self.symbol,
            total_qty=self.total_qty, executed_qty=total_executed,
            avg_price=round(avg_price, 2), benchmark_price=round(vwap_price, 2),
            slippage_bps=round(slippage_bps, 2), slices=self._slices,
            start_time=self.start_time, end_time=self.end_time,
        )


# ── Transaction Cost Analysis ─────────────────────────────────────────────────

@dataclass
class TCAReport:
    """Transaction Cost Analysis for a completed trade."""
    symbol:           str
    qty:              int
    direction:        str
    decision_price:   float   # price when trade decision was made
    executed_price:   float   # actual fill price
    arrival_slippage_bps: float    # (fill - decision) / decision * 10000
    market_impact_bps:    float    # estimated (fill - pre-trade VWAP) * 10000
    timing_cost_bps:      float    # VWAP - decision_price slippage
    brokerage_bps:        float    # brokerage + exchange fees
    total_cost_bps:       float    # all-in cost
    total_cost_inr:       float    # ₹ cost

    def __str__(self) -> str:
        return (
            f"TCA {self.symbol} {self.direction} {self.qty}:"
            f" arrival={self.arrival_slippage_bps:.1f}bps"
            f" impact={self.market_impact_bps:.1f}bps"
            f" total={self.total_cost_bps:.1f}bps (₹{self.total_cost_inr:.0f})"
        )


class TransactionCostAnalyzer:
    """
    Measures and tracks execution quality.
    Compares actual fills vs VWAP/arrival-price benchmarks.
    """

    # Indian market standard costs
    BROKERAGE_BPS   = 3.0     # 0.03% (₹20 cap)
    STT_BPS_SELL    = 1.0     # 0.01% securities transaction tax (equity sell)
    STT_BPS_FNO     = 0.5     # F&O STT
    SEBI_CHARGES    = 0.02    # bps
    STAMP_DUTY_BPS  = 0.3     # buy-side only

    def __init__(self):
        self._trades: List[TCAReport] = []

    def analyse(
        self,
        symbol:          str,
        qty:             int,
        direction:       str,
        decision_price:  float,
        executed_price:  float,
        pre_trade_vwap:  Optional[float] = None,
        is_fno:          bool = False,
    ) -> TCAReport:
        """
        Compute full TCA for one trade.

        Args:
            decision_price: mid-price at order creation time
            executed_price: actual average fill price
            pre_trade_vwap: VWAP of last N bars before order (for impact)
        """
        sign = 1 if direction == "BUY" else -1

        # Arrival slippage: how much worse than decision price
        arrival_slip = (executed_price - decision_price) / decision_price * 10000 * sign

        # Market impact vs pre-trade VWAP
        market_impact = 0.0
        if pre_trade_vwap and pre_trade_vwap > 0:
            market_impact = (executed_price - pre_trade_vwap) / pre_trade_vwap * 10000 * sign

        timing_cost = market_impact - arrival_slip

        # Transaction costs
        stt = self.STT_BPS_FNO if is_fno else (self.STT_BPS_SELL if direction == "SELL" else 0.0)
        stamp = self.STAMP_DUTY_BPS if direction == "BUY" else 0.0
        brokerage_bps = min(self.BROKERAGE_BPS, 20 / (executed_price * qty / 10000 + 1e-6))

        total_bps    = brokerage_bps + stt + self.SEBI_CHARGES + stamp
        total_cost   = total_bps + max(arrival_slip, 0)   # only count adverse slippage
        cost_inr     = executed_price * qty * total_cost / 10000

        report = TCAReport(
            symbol=symbol, qty=qty, direction=direction,
            decision_price=round(decision_price, 2),
            executed_price=round(executed_price, 2),
            arrival_slippage_bps=round(arrival_slip, 2),
            market_impact_bps=round(market_impact, 2),
            timing_cost_bps=round(timing_cost, 2),
            brokerage_bps=round(brokerage_bps, 2),
            total_cost_bps=round(total_cost, 2),
            total_cost_inr=round(cost_inr, 2),
        )
        self._trades.append(report)
        logger.info(str(report))
        return report

    def summary(self) -> pd.DataFrame:
        if not self._trades:
            return pd.DataFrame()
        return pd.DataFrame([{
            "Symbol":        t.symbol,
            "Direction":     t.direction,
            "Qty":           t.qty,
            "Arrival bps":   t.arrival_slippage_bps,
            "Impact bps":    t.market_impact_bps,
            "Total bps":     t.total_cost_bps,
            "Cost ₹":        t.total_cost_inr,
        } for t in self._trades])

    def average_cost_bps(self) -> float:
        if not self._trades:
            return 0.0
        return float(np.mean([t.total_cost_bps for t in self._trades]))
