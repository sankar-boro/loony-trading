"""
Expiry Day Strategy — BankNifty 0DTE (Zero Days to Expiry).

Why expiry day is special:
- Options lose all remaining time value by 3:30 PM → theta accelerates
- Maximum gamma: tiny moves cause large delta swings (gamma scalping window)
- Max pain pinning: option writers defend the max pain strike for OI settlement
- Gamma squeeze risk: if spot breaks key level, delta hedging creates cascade
- BankNifty weekly expiry (every Wednesday) creates 52 opportunities per year

Three sub-strategies:
1. MAX PAIN PINNING  — Sell straddle/strangle near max pain, 9:15-1:00 PM
   - Max pain strike is where total option buyer pain is maximised
   - Writers actively hedge to pin spot near max pain → mean reversion trade
   - Entry: BankNifty within ±0.5% of max pain; sell ATM straddle
   - Exit: 50% profit OR 1:00 PM time exit OR 1.5x premium stop

2. GAMMA SQUEEZE FOLLOW — Buy options when spot breaks key OI level
   - Heavy call OI buildup = resistance; heavy put OI = support
   - If spot breaks through OI wall with volume > 1.5x avg → explosive move
   - Entry: spot crosses OI wall + volume confirmation
   - Exit: 3:00 PM mandatory OR 60% profit

3. MORNING REVERSAL — Fade the opening range extreme (9:15-9:30 AM)
   - Expiry day opening gaps often reverse as market makers hedge
   - If BankNifty opens >1.5% up/down → fade the move via ATM options buy
   - Entry: 9:30 AM after opening range established
   - Exit: 11:00 AM time stop OR 50% loss stop

CRITICAL RISK RULES (0DTE):
- Never hold naked options past 2:45 PM (15 min before close)
- Max 1% capital per 0DTE trade (gamma can destroy capital instantly)
- Auto-exit all positions by 3:15 PM regardless of P&L
- Do not trade if BankNifty IV > 30% (premium already elevated = bad risk/reward)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from utils.logger import get_logger

logger = get_logger("expiry_strategy")


# ── Constants ─────────────────────────────────────────────────────────────────

BANKNIFTY_LOT_SIZE    = 15        # BankNifty lot size post Dec 2023
BANKNIFTY_STRIKE_GAP  = 100       # strike interval for BankNifty
MAX_PAIN_BAND_PCT     = 0.005     # ±0.5% around max pain for pinning entry
MAX_IV_TO_TRADE       = 0.30      # skip if ATM IV > 30%
MAX_CAPITAL_PCT       = 0.01      # max 1% capital per 0DTE trade
MANDATORY_EXIT_TIME   = time(15, 15)   # all positions closed by 3:15 PM
PINNING_PROFIT_TARGET = 0.50      # 50% premium decay for pinning trade
SQUEEZE_PROFIT_TARGET = 0.60      # 60% for squeeze follow
REVERSAL_TIME_STOP    = time(11, 0)


@dataclass
class ExpiryTrade:
    symbol:          str           # "NSE_FO|BANKNIFTY..."
    trade_type:      str           # "max_pain_pin" | "gamma_squeeze" | "morning_reversal"
    direction:       str           # "SELL_STRADDLE" | "BUY_CALL" | "BUY_PUT"
    call_strike:     float
    put_strike:      float
    call_premium:    float
    put_premium:     float
    total_premium:   float
    lots:            int
    entry_time:      datetime
    mandatory_exit:  time = field(default=MANDATORY_EXIT_TIME)
    active:          bool = True


@dataclass
class ExpiryDayContext:
    """Aggregated market context for expiry day decisions."""
    banknifty_spot:  float
    max_pain:        float
    atm_iv:          float
    pcr_oi:          float
    opening_range_high: float     # 9:15-9:30 high
    opening_range_low:  float
    heavy_call_oi_strikes: List[float] = field(default_factory=list)
    heavy_put_oi_strikes:  List[float] = field(default_factory=list)
    current_time:    Optional[datetime] = None


class ExpiryDayStrategy(BaseStrategy):
    """
    BankNifty 0DTE expiry day options strategy.

    Implements three sub-strategies based on time of day and market context.
    """

    def __init__(self, cfg: dict = None):
        super().__init__(cfg or {})
        self.lot_size         = int(self.cfg.get("lot_size", BANKNIFTY_LOT_SIZE))
        self.strike_gap       = int(self.cfg.get("strike_gap", BANKNIFTY_STRIKE_GAP))
        self.max_capital_pct  = float(self.cfg.get("max_capital_pct", MAX_CAPITAL_PCT))
        self.max_iv           = float(self.cfg.get("max_iv_to_trade", MAX_IV_TO_TRADE))
        self._active_trades:  List[ExpiryTrade] = []
        self._total_premium_collected: float    = 0.0

    # ── Helpers ───────────────────────────────────────────────────────────────

    def is_expiry_day(self, dt: Optional[date] = None) -> bool:
        """BankNifty expires every Wednesday."""
        d = dt or date.today()
        return d.weekday() == 2  # 0=Monday, 2=Wednesday

    def round_to_strike(self, price: float) -> float:
        """Round spot to nearest strike."""
        return round(price / self.strike_gap) * self.strike_gap

    def _compute_max_lots(self, premium: float, capital: float) -> int:
        max_risk    = capital * self.max_capital_pct
        lot_premium = premium * self.lot_size
        if lot_premium <= 0:
            return 0
        return max(1, int(max_risk / lot_premium))

    # ── Sub-strategy 1: Max Pain Pinning ─────────────────────────────────────

    def max_pain_pinning_signal(
        self,
        ctx:     ExpiryDayContext,
        capital: float,
    ) -> Optional[ExpiryTrade]:
        """
        Sell ATM straddle near max pain strike.
        Best entered 9:30-1:00 PM on expiry day.

        Entry conditions:
        - Spot within ±0.5% of max pain
        - ATM IV not elevated (< 30%)
        - PCR between 0.7-1.3 (balanced, not extreme)
        """
        if ctx.atm_iv > self.max_iv:
            logger.debug(f"MaxPain: ATM IV={ctx.atm_iv:.1%} too high, skip")
            return None

        dist_pct = abs(ctx.banknifty_spot - ctx.max_pain) / ctx.max_pain
        if dist_pct > MAX_PAIN_BAND_PCT:
            logger.debug(f"MaxPain: spot too far from max_pain ({dist_pct:.2%}), skip")
            return None

        if not (0.7 <= ctx.pcr_oi <= 1.3):
            logger.debug(f"MaxPain: PCR={ctx.pcr_oi:.2f} extreme, skip")
            return None

        atm_strike  = self.round_to_strike(ctx.max_pain)
        call_prem   = ctx.atm_iv * ctx.banknifty_spot * np.sqrt(1/365) * 0.4   # approx ATM call
        put_prem    = call_prem   # ATM put ≈ ATM call at-the-money
        total_prem  = call_prem + put_prem
        lots        = self._compute_max_lots(total_prem, capital)

        if lots == 0:
            return None

        logger.info(
            f"MaxPain: sell straddle @ {atm_strike} "
            f"premium={total_prem:.1f} lots={lots} "
            f"max_pain={ctx.max_pain:.0f} spot={ctx.banknifty_spot:.0f}"
        )

        self._total_premium_collected += total_prem * lots * self.lot_size

        trade = ExpiryTrade(
            symbol       = "NSE_FO|BankNifty",
            trade_type   = "max_pain_pin",
            direction    = "SELL_STRADDLE",
            call_strike  = atm_strike,
            put_strike   = atm_strike,
            call_premium = round(call_prem, 2),
            put_premium  = round(put_prem, 2),
            total_premium= round(total_prem, 2),
            lots         = lots,
            entry_time   = ctx.current_time or datetime.now(),
        )
        self._active_trades.append(trade)
        return trade

    # ── Sub-strategy 2: Gamma Squeeze Follow ─────────────────────────────────

    def gamma_squeeze_signal(
        self,
        ctx:              ExpiryDayContext,
        current_bar:      pd.Series,         # OHLCV bar
        avg_volume:       float,
        capital:          float,
    ) -> Optional[ExpiryTrade]:
        """
        Buy options when spot breaks through heavy OI wall with volume confirmation.

        Gamma squeeze mechanics:
        - MM's short calls at heavy call-OI strike must buy delta to stay hedged
        - As spot rises through call wall, delta buying begets more buying
        - Volume confirmation: current_volume > avg_volume * 1.5
        """
        if ctx.atm_iv > self.max_iv:
            return None

        volume_ratio = float(current_bar.get("volume", 0)) / (avg_volume + 1e-9)
        if volume_ratio < 1.5:
            return None

        # Determine squeeze direction
        spot = ctx.banknifty_spot
        squeeze_up   = any(spot > s * 1.001 for s in ctx.heavy_call_oi_strikes)
        squeeze_down = any(spot < s * 0.999 for s in ctx.heavy_put_oi_strikes)

        if not squeeze_up and not squeeze_down:
            return None

        direction    = "BUY_CALL" if squeeze_up else "BUY_PUT"
        target_delta = 0.40    # slightly OTM for cheaper entry
        otm_offset   = self.strike_gap * (1 if squeeze_up else -1)
        strike       = self.round_to_strike(spot) + otm_offset
        premium      = ctx.atm_iv * spot * np.sqrt(1/365) * 0.30   # OTM approx
        lots         = self._compute_max_lots(premium, capital)

        if lots == 0 or premium <= 0:
            return None

        logger.info(
            f"GammaSqueze: {direction} @ {strike} vol_ratio={volume_ratio:.1f}x "
            f"spot={spot:.0f} premium={premium:.1f}"
        )

        trade = ExpiryTrade(
            symbol        = "NSE_FO|BankNifty",
            trade_type    = "gamma_squeeze",
            direction     = direction,
            call_strike   = strike if squeeze_up else 0,
            put_strike    = strike if squeeze_down else 0,
            call_premium  = round(premium, 2) if squeeze_up else 0,
            put_premium   = round(premium, 2) if squeeze_down else 0,
            total_premium = round(premium, 2),
            lots          = lots,
            entry_time    = ctx.current_time or datetime.now(),
            mandatory_exit= time(15, 0),   # earlier exit for bought options
        )
        self._active_trades.append(trade)
        return trade

    # ── Sub-strategy 3: Morning Reversal ─────────────────────────────────────

    def morning_reversal_signal(
        self,
        ctx:           ExpiryDayContext,
        opening_gap_pct: float,            # (open - prev_close) / prev_close
        capital:       float,
    ) -> Optional[ExpiryTrade]:
        """
        Fade the opening range on expiry day.

        Logic: large opening gaps on expiry day are frequently reversed as
        market makers adjust delta hedges after overnight decay resets.
        Threshold: > ±1.5% gap.
        """
        if abs(opening_gap_pct) < 0.015:
            return None

        if ctx.atm_iv > self.max_iv:
            return None

        # Fade: gap up → buy puts; gap down → buy calls
        direction = "BUY_PUT" if opening_gap_pct > 0 else "BUY_CALL"
        spot      = ctx.banknifty_spot
        strike    = self.round_to_strike(spot)   # ATM for reversal
        premium   = ctx.atm_iv * spot * np.sqrt(1/365) * 0.4
        lots      = self._compute_max_lots(premium, capital)

        if lots == 0 or premium <= 0:
            return None

        logger.info(
            f"MorningReversal: {direction} gap={opening_gap_pct:.1%} "
            f"strike={strike} premium={premium:.1f}"
        )

        trade = ExpiryTrade(
            symbol        = "NSE_FO|BankNifty",
            trade_type    = "morning_reversal",
            direction     = direction,
            call_strike   = strike if direction == "BUY_CALL" else 0,
            put_strike    = strike if direction == "BUY_PUT"  else 0,
            call_premium  = round(premium, 2) if direction == "BUY_CALL" else 0,
            put_premium   = round(premium, 2) if direction == "BUY_PUT"  else 0,
            total_premium = round(premium, 2),
            lots          = lots,
            entry_time    = ctx.current_time or datetime.now(),
            mandatory_exit= REVERSAL_TIME_STOP,
        )
        self._active_trades.append(trade)
        return trade

    # ── Exit logic ────────────────────────────────────────────────────────────

    def should_exit(
        self,
        trade:             ExpiryTrade,
        current_call_prem: float,
        current_put_prem:  float,
        current_time:      Optional[time] = None,
    ) -> Tuple[bool, str]:
        """
        Universal exit checker for all expiry trade types.
        Returns (should_exit, reason).
        """
        if not trade.active:
            return False, ""

        now = current_time or datetime.now().time()

        # Mandatory time exit
        if now >= trade.mandatory_exit:
            trade.active = False
            return True, "mandatory_time_exit"

        current_total = current_call_prem + current_put_prem

        if trade.direction == "SELL_STRADDLE":
            # Profit target: premium decayed by target %
            decay_pct = (trade.total_premium - current_total) / trade.total_premium
            if decay_pct >= PINNING_PROFIT_TARGET:
                trade.active = False
                return True, "profit_target"
            # Stop loss: premium expanded by 50% (1.5x)
            if current_total >= trade.total_premium * 1.5:
                trade.active = False
                return True, "stop_loss"

        else:  # BUY_CALL or BUY_PUT
            if trade.direction == "BUY_CALL":
                profit_pct = (current_call_prem - trade.call_premium) / (trade.call_premium + 1e-6)
            else:
                profit_pct = (current_put_prem - trade.put_premium) / (trade.put_premium + 1e-6)

            if profit_pct >= SQUEEZE_PROFIT_TARGET:
                trade.active = False
                return True, "profit_target"
            if profit_pct <= -0.50:   # 50% loss on bought option = exit
                trade.active = False
                return True, "stop_loss"

        return False, ""

    # ── Status ────────────────────────────────────────────────────────────────

    def active_trades(self) -> List[ExpiryTrade]:
        return [t for t in self._active_trades if t.active]

    def daily_summary(self) -> dict:
        trades = self._active_trades
        return {
            "total_trades":    len(trades),
            "active":          len([t for t in trades if t.active]),
            "types":           {tt: sum(1 for t in trades if t.trade_type == tt)
                                for tt in {"max_pain_pin", "gamma_squeeze", "morning_reversal"}},
            "total_premium":   round(self._total_premium_collected, 2),
        }
