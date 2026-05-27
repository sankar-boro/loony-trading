"""
Iron Condor Strategy — Range-bound plays on Nifty / BankNifty.

Structure:
  - Sell OTM call spread  (short call + long call further OTM)
  - Sell OTM put spread   (short put  + long put  further OTM)

Risk is DEFINED — max loss = width of spread - premium received.
Best in low-vol, range-bound markets (IV Rank 50-80).

Key metrics:
  - Max profit  = net premium received
  - Max loss    = spread width - premium received
  - Breakevens  = short strikes ± net premium
  - Probability of profit ≈ (1 - |short call delta| - |short put delta|)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from data_engine.upstox.iv_surface import IVSurface
from feature_engine.greeks import Greeks, delta_to_strike
from utils.logger import get_logger

logger = get_logger("iron_condor")

RISK_FREE = 0.065


@dataclass
class IronCondorSetup:
    short_call: float
    long_call: float
    short_put: float
    long_put: float
    net_premium: float
    max_loss: float
    upper_breakeven: float
    lower_breakeven: float
    spread_width: float
    probability_profit: float
    dte: int
    atm_iv: float


class IronCondorStrategy(BaseStrategy):
    """
    Sell iron condor when IV is moderate-high and market is range-bound.

    Entry:
    - IV Rank 50-85 (not too low, not too high)
    - ADX < 25 (not trending)
    - Short strikes at 20-delta (adjustable)
    - Long strikes 50-100 points outside short strikes

    Exit:
    - 50% profit target
    - Short strike breached → adjust or close
    - DTE <= 3 → close to avoid gamma
    """
    name = "iron_condor"
    category = "options"
    preferred_regimes = ["ranging", "low_volatility"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        ocfg = cfg.get("options", {}).get("iron_condor", {})
        self.short_delta       = ocfg.get("short_delta", 0.20)
        self.spread_width      = ocfg.get("spread_width_pts", 100)  # Nifty: 100pt, BNF: 200pt
        self.iv_rank_min       = ocfg.get("iv_rank_min", 50.0)
        self.iv_rank_max       = ocfg.get("iv_rank_max", 85.0)
        self.profit_target_pct = ocfg.get("profit_target_pct", 0.50)
        self.stop_loss_pct     = ocfg.get("stop_loss_pct", 1.00)    # 100% of premium = break-even
        self.min_dte           = ocfg.get("min_dte", 7)
        self.max_dte           = ocfg.get("max_dte", 30)
        self.min_net_premium   = ocfg.get("min_net_premium", 50.0)
        self.max_adx           = ocfg.get("max_adx", 25.0)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        return None

    def generate_option_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        surface: IVSurface,
    ) -> Optional[Signal]:
        if not self.validate_df(df, 30):
            return None

        # Check trend condition — iron condor needs range-bound market
        from feature_engine.indicators import TechnicalIndicators as TI
        adx_series, _, _ = TI.adx(df)
        adx = float(adx_series.iloc[-1])
        if adx > self.max_adx:
            logger.debug(f"{symbol}: ADX {adx:.1f} too high for iron condor")
            return None

        spot = df["close"].iloc[-1]
        smile = surface.nearest_expiry()
        if smile is None:
            return None

        dte = smile.days_to_expiry
        if not (self.min_dte <= dte <= self.max_dte):
            return None

        iv_rank = surface.iv_rank_current()
        if not (self.iv_rank_min <= iv_rank <= self.iv_rank_max):
            logger.debug(f"{symbol}: IV rank {iv_rank:.1f} outside [{self.iv_rank_min}, {self.iv_rank_max}]")
            return None

        atm_iv = surface.atm_iv()
        if atm_iv <= 0:
            return None

        setup = self._build_setup(spot, dte, atm_iv, iv_rank)
        if setup is None or setup.net_premium < self.min_net_premium:
            return None

        confidence = self._score_confidence(iv_rank, adx, setup)

        logger.info(
            f"IronCondor {symbol}: {setup.short_put:.0f}P/{setup.short_call:.0f}C "
            f"wings: {setup.long_put:.0f}P/{setup.long_call:.0f}C "
            f"prem={setup.net_premium:.1f} max_loss={setup.max_loss:.1f} "
            f"POP={setup.probability_profit:.1%} IV_rank={iv_rank:.1f}"
        )

        return Signal(
            strategy=self.name,
            symbol=symbol,
            signal_type=SignalType.SELL,
            price=spot,
            stop_loss=setup.short_call + setup.spread_width * 0.5,  # approximate
            take_profit=spot,
            confidence=confidence,
            metadata={
                "strategy_subtype": "iron_condor",
                "short_call": setup.short_call,
                "long_call": setup.long_call,
                "short_put": setup.short_put,
                "long_put": setup.long_put,
                "net_premium": round(setup.net_premium, 2),
                "max_loss": round(setup.max_loss, 2),
                "upper_breakeven": round(setup.upper_breakeven, 2),
                "lower_breakeven": round(setup.lower_breakeven, 2),
                "probability_profit": round(setup.probability_profit, 3),
                "profit_target": round(setup.net_premium * self.profit_target_pct, 2),
                "stop_loss_level": round(setup.net_premium * (1 + self.stop_loss_pct), 2),
                "dte": dte,
                "iv_rank": round(iv_rank, 1),
                "atm_iv_pct": round(atm_iv * 100, 2),
                "adx": round(adx, 1),
            },
        )

    def _build_setup(
        self, spot: float, dte: int, atm_iv: float, iv_rank: float,
    ) -> Optional[IronCondorSetup]:
        try:
            sc = delta_to_strike(spot, dte, RISK_FREE, atm_iv, self.short_delta, "call")
            sp = delta_to_strike(spot, dte, RISK_FREE, atm_iv, -self.short_delta, "put")
            lc = sc + self.spread_width
            lp = sp - self.spread_width

            sc_g = Greeks(spot, sc, dte, RISK_FREE, atm_iv, "call")
            lc_g = Greeks(spot, lc, dte, RISK_FREE, atm_iv, "call")
            sp_g = Greeks(spot, sp, dte, RISK_FREE, atm_iv, "put")
            lp_g = Greeks(spot, lp, dte, RISK_FREE, atm_iv, "put")

            net_premium = (sc_g.price - lc_g.price) + (sp_g.price - lp_g.price)
            max_loss    = self.spread_width - net_premium

            pop = 1.0 - abs(sc_g.delta) - abs(sp_g.delta)

            return IronCondorSetup(
                short_call=sc, long_call=lc,
                short_put=sp,  long_put=lp,
                net_premium=net_premium,
                max_loss=max_loss,
                upper_breakeven=sc + net_premium,
                lower_breakeven=sp - net_premium,
                spread_width=self.spread_width,
                probability_profit=pop,
                dte=dte,
                atm_iv=atm_iv,
            )
        except Exception as e:
            logger.warning(f"Iron condor setup error: {e}")
            return None

    def _score_confidence(
        self, iv_rank: float, adx: float, setup: IronCondorSetup,
    ) -> float:
        score = 0.5
        # Higher IV rank within our range → more premium → better
        score += min((iv_rank - self.iv_rank_min) / (self.iv_rank_max - self.iv_rank_min), 1.0) * 0.2
        # Lower ADX → more range-bound → better
        score += max(1.0 - adx / self.max_adx, 0.0) * 0.15
        # Higher POP → better
        score += min(setup.probability_profit, 1.0) * 0.15
        return round(min(score, 0.92), 3)

    def adjustment_needed(
        self,
        spot: float,
        short_call: float,
        short_put: float,
        buffer_pct: float = 0.005,
    ) -> Optional[str]:
        """Returns 'call_side' or 'put_side' if spot is approaching a short strike."""
        if spot >= short_call * (1 - buffer_pct):
            return "call_side"
        if spot <= short_put * (1 + buffer_pct):
            return "put_side"
        return None
