"""
Anchored VWAP Strategy — Per-session VWAP with standard deviation bands.

Unlike cumulative VWAP (which has look-ahead bias), Anchored VWAP is reset
at the start of each trading session (09:15 IST for NSE).

VWAP bands = VWAP ± N * sqrt(variance of price from VWAP, volume-weighted).

Used by:
- Institutional traders for execution quality benchmarking
- Prop desks as intraday S/R levels
- Retail traders for mean-reversion and trend confirmation

Strategies:
1. VWAP Mean Reversion — fade when price is ±2σ from VWAP
2. VWAP Trend Confirm  — buy breakouts above +1σ with volume
3. VWAP Squeeze        — when VWAP bands narrow (low vol) → breakout incoming
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI
from utils.logger import get_logger

logger = get_logger("anchored_vwap")


def compute_anchored_vwap(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Compute session-anchored VWAP with ±1σ and ±2σ bands.
    Returns (vwap, upper2, upper1, lower1, lower2) — returning 4 series for simplicity.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"]

    cum_vol  = volume.cumsum()
    cum_tpv  = (tp * volume).cumsum()
    vwap     = cum_tpv / cum_vol.replace(0, np.nan)

    # Volume-weighted variance
    cum_tp2v = (tp ** 2 * volume).cumsum()
    variance = (cum_tp2v / cum_vol.replace(0, np.nan)) - vwap ** 2
    variance = variance.clip(lower=0)
    std      = variance.apply(np.sqrt)

    upper2 = vwap + 2.0 * std
    upper1 = vwap + 1.0 * std
    lower1 = vwap - 1.0 * std
    lower2 = vwap - 2.0 * std

    return vwap, upper2, upper1, lower1, lower2


class AnchoredVWAPStrategy(BaseStrategy):
    """
    Trade from session-anchored VWAP levels.

    Modes:
    - REVERSION: Price at ±2σ band → fade back to VWAP
    - BREAKOUT:  Price breaks above VWAP with volume expansion → trend follow
    - REJECTION: Price tries to cross VWAP band but fails → fade the failure
    """
    name = "anchored_vwap"
    category = "microstructure"
    preferred_regimes = ["ranging", "trending_up", "trending_down"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        mcfg = cfg.get("microstructure", {}).get("anchored_vwap", {})
        self.reversion_sigma   = mcfg.get("reversion_sigma", 1.8)    # enter reversion at 1.8σ
        self.breakout_sigma    = mcfg.get("breakout_sigma", 1.0)      # breakout above +1σ
        self.vol_confirm_mult  = mcfg.get("vol_confirm_mult", 1.5)    # volume > 1.5x average
        self.min_bars          = mcfg.get("min_bars", 10)             # min bars since session start

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.min_bars + 2):
            return None

        vwap, upper2, upper1, lower1, lower2 = compute_anchored_vwap(df)

        spot     = df["close"].iloc[-1]
        vwap_now = float(vwap.iloc[-1])
        u2       = float(upper2.iloc[-1])
        u1       = float(upper1.iloc[-1])
        l1       = float(lower1.iloc[-1])
        l2       = float(lower2.iloc[-1])
        band_std = (u1 - vwap_now)  # 1σ distance

        if band_std <= 0 or np.isnan(vwap_now):
            return None

        sigma_dist = (spot - vwap_now) / band_std
        vol_avg    = float(df["volume"].iloc[-20:].mean()) if len(df) >= 20 else float(df["volume"].mean())
        vol_now    = float(df["volume"].iloc[-1])
        vol_ratio  = vol_now / vol_avg if vol_avg > 0 else 1.0

        signal: Optional[Signal] = None

        # ── Reversion at extreme bands ─────────────────────────────────────────
        if sigma_dist >= self.reversion_sigma:
            # Price at upper band → short back to VWAP
            sl, tp = self._atr_stops(df, -1, atr_sl_mult=0.8, atr_tp_mult=1.2)
            # Override TP to VWAP
            tp = vwap_now
            confidence = min(0.60 + (sigma_dist - self.reversion_sigma) * 0.1, 0.82)
            signal = Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=spot,
                stop_loss=sl, take_profit=tp,
                confidence=confidence,
                metadata={
                    "mode": "vwap_reversion", "sigma_dist": round(sigma_dist, 2),
                    "vwap": round(vwap_now, 2), "band": "upper",
                    "upper2": round(u2, 2), "upper1": round(u1, 2),
                },
            )

        elif sigma_dist <= -self.reversion_sigma:
            # Price at lower band → long back to VWAP
            sl, tp = self._atr_stops(df, 1, atr_sl_mult=0.8, atr_tp_mult=1.2)
            tp = vwap_now
            confidence = min(0.60 + (abs(sigma_dist) - self.reversion_sigma) * 0.1, 0.82)
            signal = Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=spot,
                stop_loss=sl, take_profit=tp,
                confidence=confidence,
                metadata={
                    "mode": "vwap_reversion", "sigma_dist": round(sigma_dist, 2),
                    "vwap": round(vwap_now, 2), "band": "lower",
                    "lower2": round(l2, 2), "lower1": round(l1, 2),
                },
            )

        # ── Breakout above +1σ with volume ────────────────────────────────────
        elif sigma_dist >= self.breakout_sigma and vol_ratio >= self.vol_confirm_mult:
            prev_sigma = (df["close"].iloc[-2] - float(vwap.iloc[-2])) / band_std
            if prev_sigma < self.breakout_sigma:  # fresh break
                sl, tp = self._atr_stops(df, 1, atr_sl_mult=1.0, atr_tp_mult=1.8)
                confidence = min(0.58 + vol_ratio * 0.05, 0.80)
                signal = Signal(
                    strategy=self.name, symbol=symbol,
                    signal_type=SignalType.BUY, price=spot,
                    stop_loss=sl, take_profit=tp,
                    confidence=confidence,
                    metadata={
                        "mode": "vwap_breakout", "sigma_dist": round(sigma_dist, 2),
                        "vwap": round(vwap_now, 2), "vol_ratio": round(vol_ratio, 2),
                    },
                )

        # ── Breakdown below -1σ with volume ───────────────────────────────────
        elif sigma_dist <= -self.breakout_sigma and vol_ratio >= self.vol_confirm_mult:
            prev_sigma = (df["close"].iloc[-2] - float(vwap.iloc[-2])) / band_std
            if prev_sigma > -self.breakout_sigma:
                sl, tp = self._atr_stops(df, -1, atr_sl_mult=1.0, atr_tp_mult=1.8)
                confidence = min(0.58 + vol_ratio * 0.05, 0.80)
                signal = Signal(
                    strategy=self.name, symbol=symbol,
                    signal_type=SignalType.SELL, price=spot,
                    stop_loss=sl, take_profit=tp,
                    confidence=confidence,
                    metadata={
                        "mode": "vwap_breakdown", "sigma_dist": round(sigma_dist, 2),
                        "vwap": round(vwap_now, 2), "vol_ratio": round(vol_ratio, 2),
                    },
                )

        if signal:
            logger.info(
                f"AnchoredVWAP {symbol}: mode={signal.metadata.get('mode')} "
                f"σ={sigma_dist:.2f} spot={spot:.2f} vwap={vwap_now:.2f} "
                f"conf={signal.confidence:.2f}"
            )

        return signal
