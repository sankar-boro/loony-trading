"""
Gamma Scalping Strategy — Delta-neutral with positive gamma capture.

How it works:
1. Buy ATM straddle (own positive gamma, pay theta)
2. When spot moves, delta becomes non-zero
3. Re-hedge by trading the underlying to bring delta back to zero
4. Each hedge captures the actual move; gamma profits exceed theta paid if moves are large enough

Best used on:
- Expiry days (gamma spikes → small moves create big delta shifts)
- High-volatility events (realized vol > implied vol)
- When India VIX is rising

Key condition: Realized Volatility > Implied Volatility (gamma scalping is profitable
when the market actually moves more than IV implies).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from data_engine.upstox.iv_surface import IVSurface
from feature_engine.greeks import Greeks
from utils.logger import get_logger

logger = get_logger("gamma_scalping")

RISK_FREE = 0.065


@dataclass
class HedgeTrade:
    """Record of a single delta hedge trade."""
    spot_at_hedge: float
    delta_before: float
    hedge_qty: float        # positive = bought underlying, negative = sold
    direction: str          # "buy" or "sell"


@dataclass
class GammaPosition:
    """Tracks a live gamma scalping position."""
    call_strike: float
    put_strike: float
    straddle_cost: float
    current_delta: float = 0.0
    hedge_trades: List[HedgeTrade] = field(default_factory=list)
    total_hedge_pnl: float = 0.0
    theta_paid: float = 0.0

    def net_pnl(self, current_straddle_value: float) -> float:
        return (current_straddle_value - self.straddle_cost) + self.total_hedge_pnl


class GammaScalpingStrategy(BaseStrategy):
    """
    Delta-neutral gamma scalping.

    Entry conditions:
    - Realized vol (20-bar) > Implied vol by rv_iv_ratio_min (default 1.1x)
    - OR: DTE <= gamma_expiry_dte (expiry day gamma spike)
    - IV Rank < 60 (don't buy expensive options)

    Re-hedge trigger:
    - When delta > hedge_delta_threshold (default 0.10) → re-hedge
    """
    name = "gamma_scalping"
    category = "options"
    preferred_regimes = ["high_volatility", "all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        ocfg = cfg.get("options", {}).get("gamma_scalping", {})
        self.rv_iv_ratio_min       = ocfg.get("rv_iv_ratio_min", 1.10)
        self.hedge_delta_threshold = ocfg.get("hedge_delta_threshold", 0.10)
        self.gamma_expiry_dte      = ocfg.get("gamma_expiry_dte", 2)
        self.max_iv_rank           = ocfg.get("max_iv_rank", 60.0)
        self.min_gamma             = ocfg.get("min_gamma", 0.002)
        self.rv_lookback           = ocfg.get("rv_lookback", 20)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        return None

    def generate_option_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        surface: IVSurface,
    ) -> Optional[Signal]:
        if not self.validate_df(df, self.rv_lookback + 5):
            return None

        spot = df["close"].iloc[-1]
        smile = surface.nearest_expiry()
        if smile is None:
            return None

        dte       = smile.days_to_expiry
        iv_rank   = surface.iv_rank_current()
        atm_iv    = surface.atm_iv()

        if iv_rank > self.max_iv_rank:
            logger.debug(f"{symbol}: IV rank {iv_rank:.1f} too high — expensive to buy")
            return None

        if atm_iv <= 0:
            return None

        # Realized volatility (annualized)
        log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        rv = float(log_returns.tail(self.rv_lookback).std() * np.sqrt(252))

        expiry_mode = (dte <= self.gamma_expiry_dte)
        rv_mode     = (rv > atm_iv * self.rv_iv_ratio_min)

        if not expiry_mode and not rv_mode:
            logger.debug(
                f"{symbol}: RV={rv:.2%} IV={atm_iv:.2%} ratio={rv/atm_iv:.2f} "
                f"DTE={dte} — no gamma scalp trigger"
            )
            return None

        # ATM straddle strike (round to nearest 50 for Nifty, 100 for BankNifty)
        strike_round = 100 if "BANK" in symbol.upper() else 50
        atm_strike = round(spot / strike_round) * strike_round

        cg = Greeks(spot, atm_strike, dte, RISK_FREE, atm_iv, "call")
        pg = Greeks(spot, atm_strike, dte, RISK_FREE, atm_iv, "put")

        straddle_price = cg.price + pg.price
        total_gamma    = cg.gamma + pg.gamma
        daily_theta    = cg.theta + pg.theta   # negative (time decay cost)

        if total_gamma < self.min_gamma:
            logger.debug(f"{symbol}: gamma {total_gamma:.5f} too low — not worth scalping")
            return None

        # Break-even realized vol: RV must exceed IV for profitability
        # Approx: daily PnL from gamma = 0.5 * Gamma * S^2 * (RV^2 - IV^2)
        daily_gamma_pnl = 0.5 * total_gamma * spot ** 2 * (rv ** 2 - atm_iv ** 2) / 252
        daily_theta_cost = abs(daily_theta)

        if not expiry_mode and daily_gamma_pnl < daily_theta_cost:
            logger.debug(
                f"{symbol}: Expected gamma PnL ₹{daily_gamma_pnl:.2f} < theta ₹{daily_theta_cost:.2f}"
            )
            return None

        mode_str = "expiry_gamma" if expiry_mode else f"rv_{rv:.1%}_vs_iv_{atm_iv:.1%}"
        confidence = 0.65 if expiry_mode else min(0.55 + (rv / atm_iv - 1.0) * 0.5, 0.88)

        logger.info(
            f"GammaScalp {symbol}: buy ATM {atm_strike} straddle cost={straddle_price:.1f} "
            f"gamma={total_gamma:.5f} theta={daily_theta:.2f}/day "
            f"mode={mode_str} conf={confidence:.2f}"
        )

        return Signal(
            strategy=self.name,
            symbol=symbol,
            signal_type=SignalType.BUY,
            price=spot,
            stop_loss=spot * 0.985,
            take_profit=spot * 1.015,
            confidence=confidence,
            metadata={
                "strategy_subtype": "gamma_scalp",
                "atm_strike": atm_strike,
                "straddle_cost": round(straddle_price, 2),
                "gamma": round(total_gamma, 6),
                "daily_theta": round(daily_theta, 2),
                "realized_vol_pct": round(rv * 100, 2),
                "implied_vol_pct": round(atm_iv * 100, 2),
                "rv_iv_ratio": round(rv / atm_iv, 3),
                "expected_daily_gamma_pnl": round(daily_gamma_pnl, 2),
                "hedge_delta_threshold": self.hedge_delta_threshold,
                "dte": dte,
                "iv_rank": round(iv_rank, 1),
                "mode": mode_str,
            },
        )

    def compute_hedge(
        self,
        spot: float,
        strike: float,
        dte: int,
        sigma: float,
        current_hedge_qty: float,
        lot_size: int = 50,
    ) -> Optional[HedgeTrade]:
        """
        Compute re-hedge quantity when delta threshold is breached.
        Returns a HedgeTrade if a hedge is needed.
        """
        cg = Greeks(spot, strike, dte, RISK_FREE, sigma, "call")
        pg = Greeks(spot, strike, dte, RISK_FREE, sigma, "put")
        net_delta = cg.delta + pg.delta + current_hedge_qty / (spot * lot_size)

        if abs(net_delta) < self.hedge_delta_threshold:
            return None

        # Hedge qty to bring delta to zero
        hedge_qty = -net_delta * spot * lot_size
        hedge_qty = round(hedge_qty / lot_size) * lot_size

        if hedge_qty == 0:
            return None

        return HedgeTrade(
            spot_at_hedge=spot,
            delta_before=net_delta,
            hedge_qty=hedge_qty,
            direction="buy" if hedge_qty > 0 else "sell",
        )
