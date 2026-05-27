"""
Beta-Neutral Portfolio Construction.

Problem: If you're long 5 stocks and Nifty falls 2%, you lose ~2% regardless
of how good your stock picks are. That's MARKET BETA — not your edge.

Solution: Hedge market risk with Nifty futures so you only capture
STOCK-SPECIFIC ALPHA (the part from your actual skill).

How it works:
1. Compute each stock's rolling beta vs Nifty 50
2. Sum to get portfolio beta = Σ (position_value_i / total_capital) * β_i
3. Short Nifty futures worth (portfolio_beta * portfolio_value) to neutralise
4. Monitor and rebalance when portfolio beta drifts beyond threshold

Benefits:
- Your P&L is independent of Nifty direction → sharper Sharpe ratio
- Can be long AND short simultaneously without market-timing
- Standard structure for long-short equity funds
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger("beta_neutral")

NIFTY_LOT_SIZE  = 50      # Nifty 50 futures lot size
NIFTY_MARGIN    = 0.12    # ~12% margin for Nifty futures


@dataclass
class BetaEstimate:
    symbol:     str
    beta:       float           # rolling beta vs Nifty
    r_squared:  float           # quality of beta estimate
    lookback:   int
    updated_at: Optional[pd.Timestamp] = None


@dataclass
class HedgeOrder:
    instrument: str             # "NSE_INDEX|Nifty 50" futures
    direction: str              # "buy" or "sell"
    lots: int                   # number of lots
    notional: float             # ₹ notional
    reason: str


class BetaNeutralManager:
    """
    Maintains portfolio beta near zero by dynamically hedging with Nifty futures.

    Usage:
        bnm = BetaNeutralManager(capital=1_000_000)
        bnm.update_prices("RELIANCE", nifty_returns, stock_returns)
        hedge = bnm.compute_hedge(positions)
        if hedge:
            # place hedge order via executor
    """

    def __init__(
        self,
        capital: float,
        target_beta: float = 0.0,
        rebalance_threshold: float = 0.15,    # rebalance when |portfolio_beta| > 0.15
        beta_lookback: int = 60,
        max_hedge_pct: float = 0.80,          # max hedge = 80% of capital
    ):
        self.capital             = capital
        self.target_beta         = target_beta
        self.rebalance_threshold = rebalance_threshold
        self.beta_lookback       = beta_lookback
        self.max_hedge_pct       = max_hedge_pct
        self._betas: Dict[str, BetaEstimate]    = {}
        self._nifty_prices: Optional[pd.Series] = None
        self._current_hedge_lots: int           = 0

    def update_nifty_prices(self, nifty_prices: pd.Series) -> None:
        """Update Nifty price series used for beta computation."""
        self._nifty_prices = nifty_prices

    def compute_beta(
        self,
        symbol: str,
        stock_prices: pd.Series,
        nifty_prices: Optional[pd.Series] = None,
    ) -> BetaEstimate:
        """
        Compute rolling beta of a stock vs Nifty using OLS regression.
        β = Cov(R_stock, R_nifty) / Var(R_nifty)
        """
        if nifty_prices is None:
            nifty_prices = self._nifty_prices
        if nifty_prices is None or len(nifty_prices) < 10:
            return BetaEstimate(symbol=symbol, beta=1.0, r_squared=0.0, lookback=0)

        # Align
        merged = pd.DataFrame({
            "stock": stock_prices,
            "nifty": nifty_prices,
        }).dropna()

        if len(merged) < 10:
            return BetaEstimate(symbol=symbol, beta=1.0, r_squared=0.0, lookback=0)

        window = min(self.beta_lookback, len(merged))
        merged = merged.tail(window)

        r_stock = merged["stock"].pct_change().dropna().values
        r_nifty = merged["nifty"].pct_change().dropna().values

        min_len = min(len(r_stock), len(r_nifty))
        r_stock, r_nifty = r_stock[-min_len:], r_nifty[-min_len:]

        if len(r_nifty) < 5:
            return BetaEstimate(symbol=symbol, beta=1.0, r_squared=0.0, lookback=0)

        cov    = float(np.cov(r_stock, r_nifty)[0, 1])
        var_n  = float(np.var(r_nifty))
        beta   = cov / var_n if var_n > 1e-12 else 1.0

        # R² from correlation
        corr   = np.corrcoef(r_stock, r_nifty)[0, 1]
        r2     = float(corr**2) if not np.isnan(corr) else 0.0

        est = BetaEstimate(
            symbol=symbol, beta=round(beta, 4), r_squared=round(r2, 4),
            lookback=len(r_nifty), updated_at=pd.Timestamp.now(),
        )
        self._betas[symbol] = est
        return est

    def portfolio_beta(
        self,
        positions: Dict[str, float],   # symbol → market value (₹)
    ) -> float:
        """
        Compute weighted portfolio beta.
        portfolio_beta = Σ (w_i * β_i)
        """
        total = sum(abs(v) for v in positions.values())
        if total == 0:
            return 0.0

        weighted_beta = 0.0
        for symbol, mkt_val in positions.items():
            beta = self._betas.get(symbol, BetaEstimate(symbol, 1.0, 0.0, 0)).beta
            weight = mkt_val / total
            weighted_beta += weight * beta

        return round(weighted_beta, 4)

    def compute_hedge(
        self,
        positions: Dict[str, float],   # symbol → market value
        nifty_spot: float,
    ) -> Optional[HedgeOrder]:
        """
        Compute required Nifty futures hedge to neutralise portfolio beta.

        Returns HedgeOrder if hedge adjustment needed, else None.
        """
        port_beta = self.portfolio_beta(positions)
        total_val = sum(abs(v) for v in positions.values())

        # Beta-adjusted Nifty exposure to hedge
        target_hedge_notional = port_beta * total_val

        if abs(port_beta - self.target_beta) < self.rebalance_threshold:
            logger.debug(f"Beta={port_beta:.3f} within threshold — no hedge needed")
            return None

        # Convert to lots
        lot_value   = nifty_spot * NIFTY_LOT_SIZE
        lots_needed = int(round(abs(target_hedge_notional) / lot_value))
        lots_needed = min(lots_needed, int(self.max_hedge_pct * self.capital / lot_value))

        if lots_needed == 0:
            return None

        direction = "sell" if target_hedge_notional > 0 else "buy"
        hedge_notional = lots_needed * lot_value

        logger.info(
            f"BetaNeutral: portfolio_β={port_beta:.3f} target={self.target_beta:.1f} "
            f"→ {direction} {lots_needed} lots (₹{hedge_notional:,.0f})"
        )

        self._current_hedge_lots = lots_needed * (1 if direction == "sell" else -1)

        return HedgeOrder(
            instrument="NSE_INDEX|Nifty 50",
            direction=direction,
            lots=lots_needed,
            notional=round(hedge_notional, 2),
            reason=f"beta_hedge: portfolio_β={port_beta:.3f}",
        )

    def beta_summary(self, positions: Dict[str, float]) -> dict:
        """Return full beta breakdown for dashboard display."""
        port_beta = self.portfolio_beta(positions)
        return {
            "portfolio_beta":      port_beta,
            "target_beta":         self.target_beta,
            "hedge_needed":        abs(port_beta) > self.rebalance_threshold,
            "current_hedge_lots":  self._current_hedge_lots,
            "per_symbol_beta":     {
                s: round(self._betas[s].beta, 4)
                for s in positions if s in self._betas
            },
        }
