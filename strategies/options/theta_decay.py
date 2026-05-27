"""
Theta Decay Strategy — Sell OTM options to collect premium.

Logic:
- When IV Rank > 70 → sell OTM options (high premium, expect IV to fall)
- Sell OTM calls above resistance, OTM puts below support
- Target 25-delta options for optimal risk/reward
- Close at 50% profit or roll before expiry
- Hard stop at 200% of premium received

This is the bread-and-butter strategy of Indian F&O prop desks.
Weekly BankNifty and monthly Nifty are primary instruments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from data_engine.upstox.iv_surface import IVSurface
from feature_engine.greeks import Greeks, delta_to_strike
from utils.logger import get_logger

logger = get_logger("theta_decay")

RISK_FREE = 0.065


@dataclass
class OptionLeg:
    """Represents a single option leg in the position."""
    option_type: str        # "call" or "put"
    strike: float
    expiry: str
    premium: float          # received (positive = credit)
    delta: float
    theta: float
    instrument_key: str = ""


class ThetaDecayStrategy(BaseStrategy):
    """
    Sell OTM options when IV is elevated.

    Entry conditions:
    1. IV Rank >= iv_rank_entry (default 70)
    2. DTE between min_dte and max_dte (default 7-21 days)
    3. Spot away from strikes by at least wing_width_pct

    Exit conditions:
    - Profit target: 50% of max profit (configurable)
    - Stop loss: 200% of premium received
    - Time exit: close all positions at DTE <= 2 (avoid gamma risk)
    """
    name = "theta_decay"
    category = "options"
    preferred_regimes = ["ranging", "low_volatility"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        ocfg = cfg.get("options", {}).get("theta_decay", {})
        self.iv_rank_entry    = ocfg.get("iv_rank_entry", 70.0)
        self.iv_rank_exit     = ocfg.get("iv_rank_exit", 40.0)
        self.target_delta     = ocfg.get("target_delta", 0.25)
        self.profit_target    = ocfg.get("profit_target_pct", 0.50)  # close at 50% profit
        self.stop_mult        = ocfg.get("stop_loss_mult", 2.0)      # 200% of premium
        self.min_dte          = ocfg.get("min_dte", 7)
        self.max_dte          = ocfg.get("max_dte", 21)
        self.min_premium      = ocfg.get("min_premium", 30.0)        # min ₹30 premium

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        # Base generate_signal requires IV surface — use generate_option_signal
        return None

    def generate_option_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        surface: IVSurface,
    ) -> Optional[Signal]:
        if not self.validate_df(df, 20):
            return None

        spot = df["close"].iloc[-1]
        smile = surface.nearest_expiry()
        if smile is None:
            return None

        dte = smile.days_to_expiry
        if not (self.min_dte <= dte <= self.max_dte):
            logger.debug(f"{symbol}: DTE {dte} outside [{self.min_dte}, {self.max_dte}]")
            return None

        iv_rank = surface.iv_rank_current()
        if iv_rank < self.iv_rank_entry:
            logger.debug(f"{symbol}: IV rank {iv_rank:.1f} below entry threshold {self.iv_rank_entry}")
            return None

        atm_iv = surface.atm_iv()
        if atm_iv <= 0:
            return None

        # Find OTM call and put strikes at target_delta
        call_strike = delta_to_strike(spot, dte, RISK_FREE, atm_iv, self.target_delta, "call")
        put_strike  = delta_to_strike(spot, dte, RISK_FREE, atm_iv, self.target_delta, "put")

        call_g = Greeks(spot, call_strike, dte, RISK_FREE, atm_iv, "call")
        put_g  = Greeks(spot, put_strike,  dte, RISK_FREE, atm_iv, "put")

        call_premium = call_g.price
        put_premium  = put_g.price
        total_premium = call_premium + put_premium

        if total_premium < self.min_premium:
            logger.debug(f"{symbol}: Premium ₹{total_premium:.1f} below minimum ₹{self.min_premium}")
            return None

        # Stop loss level: if spot moves beyond wing by stop_mult * premium
        call_sl = call_strike + self.stop_mult * call_premium
        put_sl  = put_strike  - self.stop_mult * put_premium

        confidence = min(0.5 + (iv_rank - self.iv_rank_entry) / 100.0, 0.95)

        logger.info(
            f"ThetaDecay {symbol}: sell {dte}DTE strangle | "
            f"call {call_strike:.0f}({call_premium:.1f}) put {put_strike:.0f}({put_premium:.1f}) "
            f"total_prem={total_premium:.1f} IV_rank={iv_rank:.1f} conf={confidence:.2f}"
        )

        return Signal(
            strategy=self.name,
            symbol=symbol,
            signal_type=SignalType.SELL,   # sell = short options
            price=spot,
            stop_loss=call_sl,             # stop on call leg (put stop in metadata)
            take_profit=spot,              # theta decay — target is premium erosion
            confidence=confidence,
            metadata={
                "strategy_subtype": "short_strangle",
                "call_strike": call_strike,
                "put_strike": put_strike,
                "call_premium": round(call_premium, 2),
                "put_premium": round(put_premium, 2),
                "total_premium": round(total_premium, 2),
                "profit_target": round(total_premium * self.profit_target, 2),
                "call_stop": round(call_sl, 2),
                "put_stop": round(put_sl, 2),
                "dte": dte,
                "iv_rank": round(iv_rank, 1),
                "atm_iv_pct": round(atm_iv * 100, 2),
                "call_delta": round(call_g.delta, 3),
                "put_delta": round(put_g.delta, 3),
                "call_theta": round(call_g.theta, 2),
                "put_theta": round(put_g.theta, 2),
            },
        )

    def should_exit(
        self,
        entry_total_premium: float,
        current_call_price: float,
        current_put_price: float,
        dte_remaining: int,
    ) -> Optional[str]:
        """
        Returns exit reason string or None.
        Called from executor on every tick to decide when to close.
        """
        current_cost = current_call_price + current_put_price
        pnl_pct = (entry_total_premium - current_cost) / entry_total_premium

        if pnl_pct >= self.profit_target:
            return f"profit_target_{pnl_pct:.0%}"

        if current_cost > entry_total_premium * self.stop_mult:
            return f"stop_loss_{pnl_pct:.0%}"

        if dte_remaining <= 2:
            return "dte_expiry_risk"

        return None
