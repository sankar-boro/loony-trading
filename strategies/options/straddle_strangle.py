"""
Straddle / Strangle Strategy — Event-driven volatility plays.

TWO modes:
1. BUY mode (long vol) — Buy before known events (RBI policy, budget, earnings)
   - Buy ATM straddle 3-5 days before event
   - Profit from large move in either direction
   - Exit if IV crush happens before event or after event on the spike

2. SELL mode (short vol) — IV crush after event
   - Sell straddle/strangle immediately after the event when IV collapses
   - Very short hold time (same day or next day)

Straddle = ATM call + ATM put (same strike)
Strangle = OTM call + OTM put (different strikes, cheaper)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from data_engine.upstox.iv_surface import IVSurface
from feature_engine.greeks import Greeks, delta_to_strike
from utils.logger import get_logger

logger = get_logger("straddle_strangle")

RISK_FREE = 0.065


@dataclass
class StraddleSetup:
    structure: str          # "straddle" or "strangle"
    direction: str          # "buy" or "sell"
    call_strike: float
    put_strike: float
    call_premium: float
    put_premium: float
    total_premium: float
    upper_breakeven: float
    lower_breakeven: float
    atm_iv: float
    iv_rank: float
    dte: int


class StraddleStrangleStrategy(BaseStrategy):
    """
    Volatility expansion / compression plays.

    BUY conditions (long vol):
    - IV Rank < 30 (cheap options)
    - Known event within DTE window
    - Expected move (from IV) > historical average move on event

    SELL conditions (IV crush):
    - IV Rank > 75 AND event just passed (within 1 day)
    - Post-event IV collapse expected
    """
    name = "straddle_strangle"
    category = "options"
    preferred_regimes = ["all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        ocfg = cfg.get("options", {}).get("straddle_strangle", {})
        self.buy_iv_rank_max    = ocfg.get("buy_iv_rank_max", 30.0)
        self.sell_iv_rank_min   = ocfg.get("sell_iv_rank_min", 75.0)
        self.min_dte            = ocfg.get("min_dte", 3)
        self.max_dte            = ocfg.get("max_dte", 21)
        self.use_strangle       = ocfg.get("use_strangle", True)
        self.strangle_delta     = ocfg.get("strangle_delta", 0.35)
        self.profit_target_pct  = ocfg.get("profit_target_pct", 1.0)   # 100% = double premium
        self.stop_loss_pct      = ocfg.get("stop_loss_pct", 0.50)       # stop at 50% loss

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        return None

    def generate_option_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        surface: IVSurface,
        event_days_away: int = 99,
    ) -> Optional[Signal]:
        if not self.validate_df(df, 10):
            return None

        spot = df["close"].iloc[-1]
        smile = surface.nearest_expiry()
        if smile is None:
            return None

        dte = smile.days_to_expiry
        if not (self.min_dte <= dte <= self.max_dte):
            return None

        iv_rank = surface.iv_rank_current()
        atm_iv  = surface.atm_iv()
        if atm_iv <= 0:
            return None

        # Determine direction
        if iv_rank < self.buy_iv_rank_max and event_days_away <= 5:
            direction = "buy"
        elif iv_rank > self.sell_iv_rank_min:
            direction = "sell"
        else:
            return None

        setup = self._build_setup(spot, dte, atm_iv, iv_rank, direction)
        if setup is None:
            return None

        signal_type = SignalType.BUY if direction == "buy" else SignalType.SELL
        confidence  = self._score(iv_rank, dte, direction)

        expected_move_pct = atm_iv * (dte / 365.0) ** 0.5
        expected_move_abs = spot * expected_move_pct

        logger.info(
            f"{'Long' if direction=='buy' else 'Short'} {setup.structure.title()} {symbol}: "
            f"strikes {setup.put_strike:.0f}P/{setup.call_strike:.0f}C "
            f"prem={setup.total_premium:.1f} exp_move=±{expected_move_abs:.0f} "
            f"IV_rank={iv_rank:.1f} conf={confidence:.2f}"
        )

        return Signal(
            strategy=self.name,
            symbol=symbol,
            signal_type=signal_type,
            price=spot,
            stop_loss=(
                spot * 0.98 if direction == "buy"
                else setup.call_strike + setup.total_premium
            ),
            take_profit=(
                spot + expected_move_abs if direction == "buy"
                else spot
            ),
            confidence=confidence,
            metadata={
                "strategy_subtype": f"{direction}_{setup.structure}",
                "call_strike": setup.call_strike,
                "put_strike": setup.put_strike,
                "call_premium": round(setup.call_premium, 2),
                "put_premium": round(setup.put_premium, 2),
                "total_premium": round(setup.total_premium, 2),
                "upper_breakeven": round(setup.upper_breakeven, 2),
                "lower_breakeven": round(setup.lower_breakeven, 2),
                "expected_move_pct": round(expected_move_pct * 100, 2),
                "expected_move_abs": round(expected_move_abs, 2),
                "dte": dte,
                "iv_rank": round(iv_rank, 1),
                "atm_iv_pct": round(atm_iv * 100, 2),
                "event_days_away": event_days_away,
                "profit_target": round(
                    setup.total_premium * (1 + self.profit_target_pct) if direction == "buy"
                    else setup.total_premium * self.stop_loss_pct, 2
                ),
            },
        )

    def _build_setup(
        self, spot: float, dte: int, atm_iv: float, iv_rank: float, direction: str,
    ) -> Optional[StraddleSetup]:
        try:
            if self.use_strangle:
                cs = delta_to_strike(spot, dte, RISK_FREE, atm_iv, self.strangle_delta, "call")
                ps = delta_to_strike(spot, dte, RISK_FREE, atm_iv, -self.strangle_delta, "put")
                structure = "strangle"
            else:
                # ATM straddle
                cs = ps = round(spot / 50) * 50   # round to nearest 50 (Nifty standard)
                structure = "straddle"

            cg = Greeks(spot, cs, dte, RISK_FREE, atm_iv, "call")
            pg = Greeks(spot, ps, dte, RISK_FREE, atm_iv, "put")
            total = cg.price + pg.price

            return StraddleSetup(
                structure=structure,
                direction=direction,
                call_strike=cs,
                put_strike=ps,
                call_premium=cg.price,
                put_premium=pg.price,
                total_premium=total,
                upper_breakeven=cs + total,
                lower_breakeven=ps - total,
                atm_iv=atm_iv,
                iv_rank=iv_rank,
                dte=dte,
            )
        except Exception as e:
            logger.warning(f"Straddle setup error: {e}")
            return None

    def _score(self, iv_rank: float, dte: int, direction: str) -> float:
        if direction == "buy":
            # Lower IV rank = cheaper options = better
            return round(min(0.55 + (self.buy_iv_rank_max - iv_rank) / 100.0, 0.90), 3)
        else:
            # Higher IV rank = more premium = better
            return round(min(0.55 + (iv_rank - self.sell_iv_rank_min) / 50.0, 0.90), 3)
