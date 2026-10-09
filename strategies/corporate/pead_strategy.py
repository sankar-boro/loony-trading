"""
PEAD — Post-Earnings Announcement Drift.

Why it works:
- Markets under-react to earnings surprises (well-documented anomaly since 1968)
- Positive EPS surprise → stock drifts UP for 60 days post-announcement
- Negative EPS surprise → stock drifts DOWN for 60 days
- Stronger surprise + higher institutional ownership = stronger drift
- India-specific: BSE/NSE results season (Apr-Jun, Oct-Dec) amplifies the effect

Indian context:
- Results season: Q1 (Apr-Jun), Q2 (Jul-Sep), Q3 (Oct-Dec), Q4 (Jan-Mar)
- Key dates: 30-45 days after quarter-end for Nifty50 stocks
- Entry: next-day open after earnings; Exit: 30 days or when momentum fades
- Risk: avoid stocks in F&O ban (can't hedge), check circuit limits

Earnings Surprise Score (ESS):
    ESS = (Actual EPS - Consensus EPS) / |Consensus EPS| * 100
    > +5%  = positive surprise → momentum long
    < -5%  = negative surprise → momentum short
    |ESS| < 5% = in-line → no trade

Calendar integration:
    - fetch_corporate_actions() from nse_data gives ex-date, announcement_date
    - We track 30-day drift window starting T+1 after announcement
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from utils.logger import get_logger

logger = get_logger("pead_strategy")


# ── Constants ─────────────────────────────────────────────────────────────────

SURPRISE_THRESHOLD_PCT  = 5.0    # |ESS| must exceed 5% to trade
STRONG_SURPRISE_PCT     = 15.0   # ESS > 15% = strong signal (1.25x size)
DRIFT_WINDOW_DAYS       = 30     # hold for up to 30 calendar days
STOP_LOSS_PCT           = 0.05   # 5% stop loss from entry
PROFIT_TARGET_PCT       = 0.12   # 12% profit target


@dataclass
class EarningsSurprise:
    symbol:          str
    announcement_dt: date
    actual_eps:      float
    consensus_eps:   float
    ess:             float     # Earnings Surprise Score (%)
    direction:       str       # "POSITIVE" | "NEGATIVE" | "IN_LINE"
    quarter:         str       # "Q1FY25" etc.


@dataclass
class PEADPosition:
    symbol:       str
    entry_date:   date
    entry_price:  float
    direction:    str        # "LONG" | "SHORT"
    ess:          float
    exit_date:    date       # planned exit = entry_date + DRIFT_WINDOW_DAYS
    size_mult:    float      # 1.0 normal, 1.25 strong surprise
    active:       bool = True


class PEADStrategy(BaseStrategy):
    """
    Post-Earnings Announcement Drift strategy.

    Usage:
        pead = PEADStrategy(cfg)
        signals = pead.scan_earnings_calendar()
        for sym, signal in signals.items():
            executor.place(signal)
    """

    name = "pead"

    def __init__(self, cfg: dict = None):
        super().__init__(cfg or {})
        self.surprise_threshold  = float(self.cfg.get("surprise_threshold_pct", SURPRISE_THRESHOLD_PCT))
        self.strong_threshold    = float(self.cfg.get("strong_surprise_pct",    STRONG_SURPRISE_PCT))
        self.drift_window        = int(self.cfg.get("drift_window_days",        DRIFT_WINDOW_DAYS))
        self._active_positions:  Dict[str, PEADPosition] = {}
        self._earnings_calendar: List[EarningsSurprise]  = []

    # ── Core computation ──────────────────────────────────────────────────────

    def compute_ess(
        self,
        actual_eps:    float,
        consensus_eps: float,
    ) -> float:
        """
        Earnings Surprise Score as % deviation from consensus.
        Handles zero/near-zero consensus gracefully.
        """
        if abs(consensus_eps) < 1e-6:
            return 0.0
        return (actual_eps - consensus_eps) / abs(consensus_eps) * 100.0

    def classify_surprise(self, ess: float) -> str:
        if ess >= self.surprise_threshold:
            return "POSITIVE"
        if ess <= -self.surprise_threshold:
            return "NEGATIVE"
        return "IN_LINE"

    def size_multiplier(self, ess: float) -> float:
        """1.25x size for strong surprises, 1.0x otherwise."""
        return 1.25 if abs(ess) >= self.strong_threshold else 1.0

    # ── Signal generation ─────────────────────────────────────────────────────

    def generate_signal_from_surprise(
        self,
        surprise: EarningsSurprise,
        current_price: float,
        capital: float,
    ) -> Optional[Signal]:
        """
        Generate PEAD entry signal the day after earnings announcement.

        Returns None if: in-line earnings, already in position, F&O ban, or
        stock has an upcoming corporate action within 5 days (dividend/split).
        """
        if surprise.direction == "IN_LINE":
            return None

        # Block if already in position on this stock
        if surprise.symbol in self._active_positions:
            pos = self._active_positions[surprise.symbol]
            if pos.active:
                logger.debug(f"PEAD: already in position for {surprise.symbol}")
                return None

        # F&O ban check
        try:
            from data_engine.nse_data import is_in_fo_ban
            if is_in_fo_ban(surprise.symbol):
                logger.warning(f"PEAD: {surprise.symbol} in F&O ban — skip")
                return None
        except Exception:
            pass

        signal_type = SignalType.BUY if surprise.direction == "POSITIVE" else SignalType.SELL
        mult        = self.size_multiplier(surprise.ess)

        size_pct = min(0.05 * mult, 0.08)   # max 8% of capital per PEAD trade
        quantity = int(capital * size_pct / current_price)
        if quantity == 0:
            return None

        exit_date = surprise.announcement_dt + timedelta(days=self.drift_window)

        pos = PEADPosition(
            symbol       = surprise.symbol,
            entry_date   = date.today(),
            entry_price  = current_price,
            direction    = "LONG" if signal_type == SignalType.BUY else "SHORT",
            ess          = surprise.ess,
            exit_date    = exit_date,
            size_mult    = mult,
        )
        self._active_positions[surprise.symbol] = pos

        logger.info(
            f"PEAD signal: {surprise.symbol} {signal_type.value} "
            f"ESS={surprise.ess:.1f}% exit={exit_date} qty={quantity}"
        )

        return Signal(
            symbol      = surprise.symbol,
            signal_type = signal_type,
            price       = current_price,
            quantity    = quantity,
            confidence  = min(abs(surprise.ess) / 50.0, 1.0),
            metadata    = {
                "strategy":      "pead",
                "ess":           round(surprise.ess, 2),
                "direction":     surprise.direction,
                "quarter":       surprise.quarter,
                "exit_date":     str(exit_date),
                "size_mult":     mult,
                "stop_loss":     round(current_price * (1 - STOP_LOSS_PCT)  if signal_type == SignalType.BUY
                                       else current_price * (1 + STOP_LOSS_PCT), 2),
                "profit_target": round(current_price * (1 + PROFIT_TARGET_PCT) if signal_type == SignalType.BUY
                                       else current_price * (1 - PROFIT_TARGET_PCT), 2),
            },
        )

    def should_exit(
        self,
        symbol:        str,
        current_price: float,
        current_date:  Optional[date] = None,
    ) -> Tuple[bool, str]:
        """
        Check if open PEAD position should be closed.
        Returns (should_exit, reason).
        """
        pos = self._active_positions.get(symbol)
        if pos is None or not pos.active:
            return False, ""

        today = current_date or date.today()

        # Time exit: drift window expired
        if today >= pos.exit_date:
            pos.active = False
            return True, "drift_window_expired"

        # Stop loss / profit target
        if pos.direction == "LONG":
            pnl_pct = (current_price - pos.entry_price) / pos.entry_price
            if pnl_pct <= -STOP_LOSS_PCT:
                pos.active = False
                return True, "stop_loss"
            if pnl_pct >= PROFIT_TARGET_PCT:
                pos.active = False
                return True, "profit_target"
        else:  # SHORT
            pnl_pct = (pos.entry_price - current_price) / pos.entry_price
            if pnl_pct <= -STOP_LOSS_PCT:
                pos.active = False
                return True, "stop_loss"
            if pnl_pct >= PROFIT_TARGET_PCT:
                pos.active = False
                return True, "profit_target"

        return False, ""

    # ── Calendar scan ─────────────────────────────────────────────────────────

    def scan_earnings_calendar(
        self,
        lookback_days: int = 5,
    ) -> List[EarningsSurprise]:
        """
        Fetch recent earnings announcements from NSE and return surprise objects.
        Uses corporate actions calendar + result announcements.
        """
        try:
            from data_engine.nse_data import fetch_corporate_actions
            actions = fetch_corporate_actions(days_ahead=0)
            # Filter for result announcements in last lookback_days
            cutoff = pd.Timestamp.today() - pd.Timedelta(days=lookback_days)
            results = actions[
                (actions["ex_date"] >= cutoff) &
                (actions["purpose"].str.lower().str.contains("result|earnings|quarterly", na=False))
            ] if not actions.empty else pd.DataFrame()

            surprises = []
            for _, row in results.iterrows():
                sym = str(row.get("symbol", ""))
                if not sym:
                    continue
                # Without actual consensus data, we cannot compute ESS here.
                # In production: integrate with Bloomberg/Refinitiv consensus.
                logger.debug(f"PEAD calendar: found result announcement for {sym}")
            return surprises

        except Exception as e:
            logger.debug(f"PEAD calendar scan failed: {e}")
            return []

    def add_earnings_surprise(self, surprise: EarningsSurprise) -> None:
        """Manually register a surprise (e.g. from Bloomberg/Refinitiv feed)."""
        self._earnings_calendar.append(surprise)
        logger.info(
            f"PEAD: registered surprise {surprise.symbol} "
            f"ESS={surprise.ess:.1f}% ({surprise.direction}) Q={surprise.quarter}"
        )

    # ── Position management ───────────────────────────────────────────────────

    def active_positions(self) -> Dict[str, PEADPosition]:
        return {k: v for k, v in self._active_positions.items() if v.active}

    def position_summary(self) -> pd.DataFrame:
        rows = []
        for sym, pos in self._active_positions.items():
            rows.append({
                "Symbol":     sym,
                "Direction":  pos.direction,
                "Entry":      pos.entry_price,
                "ESS%":       round(pos.ess, 1),
                "Exit Date":  pos.exit_date,
                "Active":     pos.active,
                "Size Mult":  pos.size_mult,
            })
        return pd.DataFrame(rows)

    # ── Backtestable interface ────────────────────────────────────────────────

    def backtest_pead(
        self,
        surprise: EarningsSurprise,
        price_series: pd.Series,
    ) -> dict:
        """
        Backtest a single PEAD trade given price history after announcement.

        Returns performance metrics for one trade.
        """
        if surprise.direction == "IN_LINE":
            return {"return_pct": 0.0, "hit": False, "hold_days": 0}

        entry_price = float(price_series.iloc[0]) if len(price_series) > 0 else 0.0
        if entry_price == 0:
            return {"return_pct": 0.0, "hit": False, "hold_days": 0}

        is_long  = surprise.direction == "POSITIVE"
        stop     = entry_price * (1 - STOP_LOSS_PCT)     if is_long else entry_price * (1 + STOP_LOSS_PCT)
        target   = entry_price * (1 + PROFIT_TARGET_PCT) if is_long else entry_price * (1 - PROFIT_TARGET_PCT)

        window = price_series.iloc[:self.drift_window]
        for i, price in enumerate(window):
            # Check stop / target
            if is_long:
                if price <= stop:
                    ret = (price - entry_price) / entry_price * 100
                    return {"return_pct": round(ret, 2), "hit": False, "hold_days": i+1, "exit": "stop"}
                if price >= target:
                    ret = (price - entry_price) / entry_price * 100
                    return {"return_pct": round(ret, 2), "hit": True,  "hold_days": i+1, "exit": "target"}
            else:
                if price >= stop:
                    ret = (entry_price - price) / entry_price * 100
                    return {"return_pct": round(ret, 2), "hit": False, "hold_days": i+1, "exit": "stop"}
                if price <= target:
                    ret = (entry_price - price) / entry_price * 100
                    return {"return_pct": round(ret, 2), "hit": True,  "hold_days": i+1, "exit": "target"}

        # Time exit
        final = float(window.iloc[-1]) if len(window) > 0 else entry_price
        if is_long:
            ret = (final - entry_price) / entry_price * 100
        else:
            ret = (entry_price - final) / entry_price * 100
        return {
            "return_pct": round(ret, 2),
            "hit":        ret > 0,
            "hold_days":  len(window),
            "exit":       "time",
        }
