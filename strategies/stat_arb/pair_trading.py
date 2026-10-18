"""
Kalman-filter pair trading with Engle-Granger cointegration test.

Improvements over rolling-OLS version:
- Dynamic hedge ratio via Kalman filter (updates every bar)
- Statistical cointegration test guards against spurious pairs
- OU half-life calibration auto-sizes the entry/exit z-score window
- Uncertainty-weighted position sizing (smaller when hedge ratio uncertain)
- Spread z-score from Kalman-smoothed mean (not naive rolling)

Good pairs for Nifty50 universe:
  HDFCBANK / ICICIBANK, TCS / INFY, RELIANCE / ONGC,
  AXISBANK / KOTAKBANK, BAJFINANCE / BAJAJFINSV
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from utils.kalman import KalmanHedgeRatio, coint_critical_value, engle_granger_stat, half_life
from utils.logger import get_logger

logger = get_logger("pair_trading")


@dataclass
class PairState:
    """One evaluation of a pair on its latest bar."""
    beta: float              # hedge ratio: spread = A − (beta × B + alpha)
    spread: float
    z: float                 # spread in standard deviations of the lookback window
    coint_stat: float        # Engle-Granger ADF statistic (more negative = better)
    half_life: float         # bars
    tradable: bool
    reason: str = ""         # why not tradable

    def entry_sides(self, entry_z: float) -> Optional[Tuple[SignalType, SignalType]]:
        """(side A, side B) when the spread is stretched past ±entry_z."""
        if not self.tradable or abs(self.z) < entry_z:
            return None
        if self.z > 0:                       # A rich vs B: short A, long B
            return SignalType.SELL, SignalType.BUY
        return SignalType.BUY, SignalType.SELL


class PairTradingStrategy(BaseStrategy):
    """
    Cointegration-based stat-arb. The hedge ratio is an OLS fit over the
    lookback window (`pair_hedge: ols`), or a Kalman filter seeded from it
    (`pair_hedge: kalman`).

    Each evaluation is stateless: the hedge ratio, spread z-score,
    cointegration statistic and half-life are recomputed from the last
    `pair_lookback` aligned bars, so calling it twice on the same bar gives
    the same answer and a backtest never sees the future.

    - z > entry_z  → short A, long B   (spread position −1)
    - z < −entry_z → long A, short B   (spread position +1)
    - exit when the spread reverts inside ±exit_z, or stop at ±stop_z
    - a pair whose spread is not cointegrated, or whose half-life is outside
      [min_half_life, max_half_life], is not traded

    A pair always has a short leg, so it needs a product that can hold one
    (MIS intraday, or futures); see risk_manager.can_open_short.
    """
    name = "pair_trading"
    category = "stat_arb"
    preferred_regimes = ["ranging", "all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.entry_z          = self.param("pair_entry_z", 2.0)
        self.exit_z           = self.param("pair_exit_z", 0.5)
        self.stop_z           = self.param("pair_stop_z", 4.0)
        self.min_half_life    = self.param("pair_min_half_life", 2.0)
        self.max_half_life    = self.param("pair_max_half_life", 60.0)
        self.min_history      = self.param("pair_min_history", 120)
        self.lookback         = self.param("pair_lookback", 250)
        self.coint_pvalue     = self.param("pair_coint_pvalue", 0.05)
        self.hedge            = self.param("pair_hedge", "ols")      # "ols" | "kalman"
        self.kalman_delta     = self.param("pair_kalman_delta", 1e-5)
        self.capital_pct      = self.param("pair_capital_pct", 0.10)   # gross per leg A

    # ── Evaluation ────────────────────────────────────────────────────────────

    @staticmethod
    def align(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"a": df_a["close"], "b": df_b["close"]}).dropna()

    def evaluate(self, merged: pd.DataFrame) -> Optional[PairState]:
        """Evaluate the pair on aligned closes (columns a, b); None if there
        is not enough history."""
        if len(merged) < self.min_history:
            return None
        window = merged.iloc[-self.lookback:]
        y = window["a"].to_numpy(dtype=float)
        x = window["b"].to_numpy(dtype=float)
        # Static hedge ratio over the window (OLS with an intercept)
        beta, alpha = np.polyfit(x, y, 1)
        if self.hedge == "kalman":
            # Time-varying hedge ratio. Observation noise is set to the OLS
            # residual variance; a tiny observation noise would let beta chase
            # every bar and absorb the very spread being traded.
            kf = KalmanHedgeRatio(delta=self.kalman_delta,
                                  vt=float(np.var(y - (beta * x + alpha))) or 1e-3)
            kf.theta[:] = [beta, alpha]
            kf.fit(window["a"], window["b"])
            beta, alpha = kf.beta, kf.alpha
        spreads = y - (beta * x + alpha)
        sd = float(np.std(spreads))
        spread = float(spreads[-1])
        z = spread / sd if sd > 1e-12 else float("nan")
        stat = engle_granger_stat(y, x)
        hl = half_life(spreads)
        reason = ""
        if not np.isfinite(z):
            reason = "no z-score"
        elif stat >= coint_critical_value(self.coint_pvalue):
            reason = f"not cointegrated (ADF {stat:.2f})"
        elif beta <= 0:
            reason = f"hedge ratio {beta:.2f} ≤ 0"
        elif not (self.min_half_life <= hl <= self.max_half_life):
            reason = f"half-life {hl:.1f} bars outside {self.min_half_life:g}–{self.max_half_life:g}"
        return PairState(beta=beta, spread=spread, z=z, coint_stat=stat,
                         half_life=hl, tradable=not reason, reason=reason)

    def exit_reason(self, state: PairState, position: int, bars_held: int = 0) -> Optional[str]:
        """Why to close an open spread position (+1 long A / short B, −1 the
        reverse) now, or None."""
        if self.max_hold_bars and bars_held >= self.max_hold_bars:
            return f"time stop ({bars_held} bars)"
        z = state.z
        if position == 1:
            if z >= -self.exit_z:
                return f"spread reverted (z {z:+.2f})"
            if z <= -self.stop_z:
                return f"spread stop (z {z:+.2f})"
        elif position == -1:
            if z <= self.exit_z:
                return f"spread reverted (z {z:+.2f})"
            if z >= self.stop_z:
                return f"spread stop (z {z:+.2f})"
        return None

    def leg_quantities(self, state: PairState, price_a: float, capital: float) -> Tuple[int, int]:
        """Shares of A (capital × pair_capital_pct) and the beta-hedged shares of B."""
        qty_a = int(capital * self.capital_pct // price_a)
        qty_b = int(round(qty_a * state.beta))
        return qty_a, qty_b

    # ── Signals (engine API) ─────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        return None   # Pairs need two series — use generate_pair_signals

    def generate_pair_signals(
        self,
        df_a: pd.DataFrame,
        df_b: pd.DataFrame,
        symbol_a: str,
        symbol_b: str,
    ) -> Tuple[Optional[Signal], Optional[Signal]]:
        merged = self.align(df_a, df_b)
        state = self.evaluate(merged)
        sides = state.entry_sides(self.entry_z) if state else None
        if not sides:
            return None, None
        confidence = self.scaled_confidence((abs(state.z) - self.entry_z) / max(self.stop_z - self.entry_z, 1e-9))
        logger.info(f"Pair {symbol_a}/{symbol_b}: z={state.z:.2f} β={state.beta:.3f} "
                    f"ADF={state.coint_stat:.2f} hl={state.half_life:.1f} conf={confidence:.2f}")
        return self._make_signals(symbol_a, symbol_b,
                                  float(merged["a"].iloc[-1]), float(merged["b"].iloc[-1]),
                                  sides[0], sides[1], state, confidence)

    def _make_signals(
        self,
        sym_a: str, sym_b: str,
        px_a: float, px_b: float,
        type_a: SignalType, type_b: SignalType,
        state: PairState, confidence: float,
    ) -> Tuple[Signal, Signal]:
        # The pair is managed on its spread (exit_reason); the per-leg stops
        # are only disaster stops, wide enough not to break the hedge.
        sl_pct = self.param("pair_leg_stop_pct", 0.06)
        tp_pct = self.param("pair_leg_target_pct", 0.20)

        def sl(px: float, side: SignalType) -> float:
            return px * (1 + sl_pct) if side == SignalType.SELL else px * (1 - sl_pct)

        def tp(px: float, side: SignalType) -> float:
            return px * (1 - tp_pct) if side == SignalType.SELL else px * (1 + tp_pct)

        meta = {"spread_z": round(state.z, 3), "beta": round(state.beta, 4),
                "pair": f"{sym_a}/{sym_b}", "entry_z": self.entry_z,
                "half_life": round(state.half_life, 1), "adf": round(state.coint_stat, 2)}
        sig_a = Signal(strategy=self.name, symbol=sym_a, signal_type=type_a, price=px_a,
                       stop_loss=sl(px_a, type_a), take_profit=tp(px_a, type_a),
                       confidence=confidence, metadata={**meta, "leg": "A"})
        sig_b = Signal(strategy=self.name, symbol=sym_b, signal_type=type_b, price=px_b,
                       stop_loss=sl(px_b, type_b), take_profit=tp(px_b, type_b),
                       confidence=confidence, metadata={**meta, "leg": "B"})
        return sig_a, sig_b
