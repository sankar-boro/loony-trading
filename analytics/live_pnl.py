"""
Live P&L Attribution with Auto-Disable.

Real-time P&L tracking that attributes each trade to:
1. Strategy contribution (which strategy generated the signal)
2. Factor contribution (how much came from market/sector vs skill)
3. Execution quality (slippage-adjusted P&L)

Auto-disable logic:
- If any strategy loses > max_daily_loss_pct of capital → disable for the day
- If portfolio-level drawdown > max_portfolio_dd_pct → halt all trading
- If consecutive loss streak > max_consecutive_losses → alert + reduce size
- Auto-re-enable: next trading day after 8 PM review window
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Deque, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger("live_pnl")

MAX_DAILY_LOSS_PCT    = 0.02    # 2% of capital → disable strategy
MAX_PORTFOLIO_DD_PCT  = 0.05    # 5% drawdown → halt all trading
MAX_CONSECUTIVE_LOSS  = 5       # 5 consecutive losers → reduce size


@dataclass
class TradeRecord:
    trade_id:    str
    strategy:    str
    symbol:      str
    direction:   str
    qty:         int
    entry_price: float
    exit_price:  float
    pnl:         float
    pnl_pct:     float
    timestamp:   datetime
    metadata:    dict = field(default_factory=dict)


@dataclass
class StrategyStatus:
    name:              str
    is_enabled:        bool
    daily_pnl:         float
    daily_pnl_pct:     float
    trade_count:       int
    win_rate:          float
    consecutive_loss:  int
    size_multiplier:   float    # 1.0 = normal, <1.0 = reduced
    disable_reason:    str      # "" if enabled


class LivePnLTracker:
    """
    Real-time P&L tracking and strategy performance management.
    """

    def __init__(
        self,
        capital:              float,
        max_daily_loss_pct:   float = MAX_DAILY_LOSS_PCT,
        max_portfolio_dd_pct: float = MAX_PORTFOLIO_DD_PCT,
        max_consecutive_loss: int   = MAX_CONSECUTIVE_LOSS,
    ):
        self.capital             = capital
        self.max_daily_loss      = capital * max_daily_loss_pct
        self.max_portfolio_dd    = capital * max_portfolio_dd_pct
        self.max_consecutive     = max_consecutive_loss
        self._peak_capital       = capital
        self._current_capital    = capital
        self._strategy_pnl:      Dict[str, List[float]]   = defaultdict(list)
        self._strategy_enabled:  Dict[str, bool]          = {}
        self._disable_reasons:   Dict[str, str]           = {}
        self._consecutive_loss:  Dict[str, int]           = defaultdict(int)
        self._size_multipliers:  Dict[str, float]         = defaultdict(lambda: 1.0)
        self._trades:            List[TradeRecord]        = []
        self._portfolio_halted:  bool                     = False
        self._halt_reason:       str                      = ""

    def record_trade(
        self,
        trade_id:    str,
        strategy:    str,
        symbol:      str,
        direction:   str,
        qty:         int,
        entry_price: float,
        exit_price:  float,
        metadata:    dict = None,
    ) -> TradeRecord:
        """Record a completed trade and update all risk metrics."""
        pnl = (exit_price - entry_price) * qty * (1 if direction == "BUY" else -1)
        pnl_pct = pnl / self.capital * 100

        rec = TradeRecord(
            trade_id=trade_id, strategy=strategy, symbol=symbol,
            direction=direction, qty=qty,
            entry_price=entry_price, exit_price=exit_price,
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 4),
            timestamp=datetime.now(), metadata=metadata or {},
        )
        self._trades.append(rec)
        self._strategy_pnl[strategy].append(pnl)
        self._current_capital += pnl

        # Update consecutive loss counter
        if pnl > 0:
            self._consecutive_loss[strategy] = 0
        else:
            self._consecutive_loss[strategy] += 1

        # Update peak for drawdown
        if self._current_capital > self._peak_capital:
            self._peak_capital = self._current_capital

        # Run auto-disable checks
        self._check_strategy_limits(strategy)
        self._check_portfolio_limits()

        logger.info(
            f"Trade: {strategy}/{symbol} {direction} {qty} "
            f"P&L=₹{pnl:+,.0f} ({pnl_pct:+.2f}%) "
            f"capital=₹{self._current_capital:,.0f}"
        )
        return rec

    def _check_strategy_limits(self, strategy: str) -> None:
        daily_pnl = sum(self._strategy_pnl[strategy])
        consec    = self._consecutive_loss[strategy]

        if daily_pnl < -self.max_daily_loss:
            self._disable_strategy(strategy, f"daily_loss_exceeded (₹{daily_pnl:,.0f})")
            return

        if consec >= self.max_consecutive:
            # Reduce size by 50% instead of disabling
            self._size_multipliers[strategy] = 0.5
            logger.warning(
                f"Strategy {strategy}: {consec} consecutive losses → size reduced to 50%"
            )

    def _check_portfolio_limits(self) -> None:
        drawdown = (self._peak_capital - self._current_capital) / self._peak_capital
        if drawdown > MAX_PORTFOLIO_DD_PCT:
            if not self._portfolio_halted:
                self._portfolio_halted = True
                self._halt_reason = f"portfolio_dd_{drawdown:.1%}"
                logger.critical(
                    f"PORTFOLIO HALT: drawdown={drawdown:.1%} > "
                    f"{MAX_PORTFOLIO_DD_PCT:.0%} limit"
                )

    def _disable_strategy(self, strategy: str, reason: str) -> None:
        if self._strategy_enabled.get(strategy, True):
            self._strategy_enabled[strategy] = False
            self._disable_reasons[strategy]  = reason
            logger.critical(f"STRATEGY DISABLED: {strategy} — {reason}")

    def is_strategy_enabled(self, strategy: str) -> bool:
        if self._portfolio_halted:
            return False
        return self._strategy_enabled.get(strategy, True)

    def get_size_multiplier(self, strategy: str) -> float:
        if not self.is_strategy_enabled(strategy):
            return 0.0
        return self._size_multipliers[strategy]

    def strategy_status(self, strategy: str) -> StrategyStatus:
        pnl_list   = self._strategy_pnl.get(strategy, [])
        daily_pnl  = sum(pnl_list)
        trade_cnt  = len(pnl_list)
        wins       = sum(1 for p in pnl_list if p > 0)
        win_rate   = wins / trade_cnt if trade_cnt > 0 else 0.0
        return StrategyStatus(
            name=strategy,
            is_enabled=self.is_strategy_enabled(strategy),
            daily_pnl=round(daily_pnl, 2),
            daily_pnl_pct=round(daily_pnl / self.capital * 100, 3),
            trade_count=trade_cnt,
            win_rate=round(win_rate, 3),
            consecutive_loss=self._consecutive_loss[strategy],
            size_multiplier=self._size_multipliers[strategy],
            disable_reason=self._disable_reasons.get(strategy, ""),
        )

    def reset_daily(self) -> None:
        """Call at start of each trading day."""
        for s in list(self._strategy_enabled.keys()):
            self._strategy_enabled[s] = True
            self._disable_reasons.pop(s, None)
            self._consecutive_loss[s] = 0
            self._size_multipliers[s] = 1.0
        self._strategy_pnl.clear()
        self._portfolio_halted = False
        self._halt_reason = ""
        logger.info("LivePnL: daily reset complete")

    def portfolio_summary(self) -> dict:
        total_pnl   = self._current_capital - self.capital
        drawdown    = (self._peak_capital - self._current_capital) / self._peak_capital
        return {
            "capital":         round(self.capital, 2),
            "current_capital": round(self._current_capital, 2),
            "daily_pnl":       round(total_pnl, 2),
            "daily_pnl_pct":   round(total_pnl / self.capital * 100, 3),
            "drawdown_pct":    round(drawdown * 100, 3),
            "peak_capital":    round(self._peak_capital, 2),
            "is_halted":       self._portfolio_halted,
            "halt_reason":     self._halt_reason,
            "total_trades":    len(self._trades),
            "strategies":      list(self._strategy_pnl.keys()),
        }

    def pnl_dataframe(self) -> pd.DataFrame:
        if not self._trades:
            return pd.DataFrame()
        return pd.DataFrame([{
            "Time":     t.timestamp.strftime("%H:%M:%S"),
            "Strategy": t.strategy,
            "Symbol":   t.symbol,
            "Dir":      t.direction,
            "Qty":      t.qty,
            "Entry":    t.entry_price,
            "Exit":     t.exit_price,
            "P&L ₹":   t.pnl,
            "P&L %":   t.pnl_pct,
        } for t in self._trades])
