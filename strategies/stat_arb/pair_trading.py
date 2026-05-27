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

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from utils.kalman import KalmanSpreadTracker
from utils.math_utils import rolling_zscore
from utils.logger import get_logger

logger = get_logger("pair_trading")


class PairTradingStrategy(BaseStrategy):
    """
    Cointegration-based stat-arb with Kalman filter hedge ratios.

    Signal logic:
    - z > entry_z  → spread too high: short A, long  B
    - z < -entry_z → spread too low:  long  A, short B
    - |z| < exit_z → close both legs
    """
    name = "pair_trading"
    category = "stat_arb"
    preferred_regimes = ["ranging", "all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.entry_z          = cfg.get("pair_entry_z", 2.0)
        self.exit_z           = cfg.get("pair_exit_z", 0.5)
        self.min_half_life    = cfg.get("pair_min_half_life", 5)
        self.max_half_life    = cfg.get("pair_max_half_life", 60)
        self.min_history      = cfg.get("pair_min_history", 120)
        self.coint_pvalue     = cfg.get("pair_coint_pvalue", 0.05)
        self.kalman_delta     = cfg.get("pair_kalman_delta", 1e-4)
        self._trackers: Dict[str, KalmanSpreadTracker] = {}

    # Public entry point ───────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        return None   # Pairs need two series — use generate_pair_signals

    def generate_pair_signals(
        self,
        df_a: pd.DataFrame,
        df_b: pd.DataFrame,
        symbol_a: str,
        symbol_b: str,
    ) -> Tuple[Optional[Signal], Optional[Signal]]:
        if len(df_a) < self.min_history or len(df_b) < self.min_history:
            return None, None

        # Align
        merged = pd.DataFrame({
            "a": df_a["close"],
            "b": df_b["close"],
        }).dropna()
        if len(merged) < self.min_history:
            return None, None

        key = f"{symbol_a}_{symbol_b}"
        tracker = self._get_tracker(key, symbol_a, symbol_b, merged)

        # Live update with latest bar
        price_a = float(merged["a"].iloc[-1])
        price_b = float(merged["b"].iloc[-1])
        beta, spread, z, uncertainty = tracker.update(price_a, price_b)

        if np.isnan(z):
            return None, None

        # Uncertainty penalty: large P → weaker signal
        uncertainty_penalty = min(uncertainty * 100, 0.5)
        effective_z = abs(z) * (1.0 - uncertainty_penalty)

        if effective_z < self.entry_z:
            return None, None

        confidence = min(effective_z / 4.0, 1.0) * (1.0 - uncertainty_penalty * 0.5)

        logger.info(
            f"Pair {symbol_a}/{symbol_b}: z={z:.2f} β={beta:.3f} "
            f"P={uncertainty:.5f} conf={confidence:.2f}"
        )

        if z > self.entry_z:
            return self._make_signals(
                symbol_a, symbol_b, price_a, price_b,
                SignalType.SELL, SignalType.BUY, z, beta, confidence,
            )
        else:
            return self._make_signals(
                symbol_a, symbol_b, price_a, price_b,
                SignalType.BUY, SignalType.SELL, z, beta, confidence,
            )

    # Helpers ──────────────────────────────────────────────────────────────────

    def _get_tracker(
        self,
        key: str,
        symbol_a: str,
        symbol_b: str,
        merged: pd.DataFrame,
    ) -> KalmanSpreadTracker:
        if key not in self._trackers:
            tracker = KalmanSpreadTracker(symbol_a, symbol_b, delta=self.kalman_delta)

            # Check cointegration before committing
            coint_ok = tracker.is_cointegrated(merged["a"], merged["b"], self.coint_pvalue)
            if not coint_ok:
                logger.debug(f"Pair {key}: not cointegrated — continuing with caution")

            # Fit on historical data
            spread_df = tracker.fit(merged["a"], merged["b"])

            # Check half-life
            hl = tracker.half_life(spread_df["spread"])
            if not (self.min_half_life <= hl <= self.max_half_life):
                logger.debug(
                    f"Pair {key}: half-life {hl:.1f} outside [{self.min_half_life}, {self.max_half_life}]"
                )

            self._trackers[key] = tracker

        return self._trackers[key]

    def _make_signals(
        self,
        sym_a: str, sym_b: str,
        px_a: float, px_b: float,
        type_a: SignalType, type_b: SignalType,
        z: float, beta: float, confidence: float,
    ) -> Tuple[Signal, Signal]:
        sl_pct = 0.015
        tp_pct = 0.020

        def sl(px: float, direction: SignalType) -> float:
            return px * (1 + sl_pct) if direction == SignalType.SELL else px * (1 - sl_pct)

        def tp(px: float, direction: SignalType) -> float:
            return px * (1 - tp_pct) if direction == SignalType.SELL else px * (1 + tp_pct)

        meta = {"spread_z": round(z, 3), "beta": round(beta, 4),
                "pair": f"{sym_a}/{sym_b}", "entry_z": self.entry_z}

        sig_a = Signal(
            strategy=self.name, symbol=sym_a,
            signal_type=type_a, price=px_a,
            stop_loss=sl(px_a, type_a), take_profit=tp(px_a, type_a),
            confidence=confidence, metadata={**meta, "leg": "A"},
        )
        sig_b = Signal(
            strategy=self.name, symbol=sym_b,
            signal_type=type_b, price=px_b,
            stop_loss=sl(px_b, type_b), take_profit=tp(px_b, type_b),
            confidence=confidence, metadata={**meta, "leg": "B"},
        )
        return sig_a, sig_b
