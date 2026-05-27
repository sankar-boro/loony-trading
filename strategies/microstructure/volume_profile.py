"""
Volume Profile Strategy — Trade from high-volume price nodes.

Volume Profile maps how much volume traded at each price level.
Key levels:
  - POC  (Point of Control)    — highest volume price → strongest S/R
  - VAH  (Value Area High)     — top of 70% volume cluster
  - VAL  (Value Area Low)      — bottom of 70% volume cluster
  - HVN  (High Volume Node)    — price acceptance zones (support/resistance)
  - LVN  (Low Volume Node)     — price rejection zones (price moves fast through these)

Edge:
- Price returning to POC → high probability bounce
- Price breaking through LVN → momentum continuation (no support)
- Price accepting above VAH → bullish rotation (value area shift)
- Price rejecting at HVN near current session → fade the level
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from utils.logger import get_logger

logger = get_logger("volume_profile")


@dataclass
class VolumeProfileLevels:
    poc: float              # Point of Control
    vah: float              # Value Area High
    val: float              # Value Area Low
    hvn_levels: List[float] # High Volume Nodes (besides POC)
    lvn_levels: List[float] # Low Volume Nodes
    total_volume: float
    price_bins: np.ndarray
    volume_bins: np.ndarray


def compute_volume_profile(
    df: pd.DataFrame,
    bins: int = 100,
    value_area_pct: float = 0.70,
) -> Optional[VolumeProfileLevels]:
    """
    Compute volume profile from OHLCV data.

    Uses VWAP-style distribution: volume is spread across the bar's range
    proportionally to estimate which price levels saw the most activity.
    """
    if df.empty or len(df) < 5:
        return None

    price_min = float(df["low"].min())
    price_max = float(df["high"].max())
    if price_min >= price_max:
        return None

    price_bins = np.linspace(price_min, price_max, bins + 1)
    vol_dist   = np.zeros(bins)
    bin_width  = (price_max - price_min) / bins

    for _, row in df.iterrows():
        lo, hi, vol = row["low"], row["high"], row["volume"]
        if hi == lo:
            idx = int((lo - price_min) / bin_width)
            idx = max(0, min(idx, bins - 1))
            vol_dist[idx] += vol
        else:
            # Distribute volume across the bar's range proportionally
            bar_bins = (price_bins[:-1] >= lo) & (price_bins[:-1] <= hi)
            count = bar_bins.sum()
            if count > 0:
                vol_dist[bar_bins] += vol / count

    total_vol = vol_dist.sum()
    if total_vol == 0:
        return None

    # POC: highest volume bin centre
    poc_idx = int(np.argmax(vol_dist))
    poc = float(price_bins[poc_idx] + bin_width / 2)

    # Value Area: bins contributing to 70% of volume, starting from POC
    vol_sorted_idx = np.argsort(vol_dist)[::-1]
    cumvol = 0.0
    va_indices = set()
    for idx in vol_sorted_idx:
        va_indices.add(idx)
        cumvol += vol_dist[idx]
        if cumvol >= total_vol * value_area_pct:
            break

    va_prices = price_bins[[i for i in va_indices]]
    vah = float(va_prices.max() + bin_width)
    val = float(va_prices.min())

    # HVN: bins in top quartile excluding POC
    hvn_threshold = np.percentile(vol_dist, 75)
    hvn_levels = [
        float(price_bins[i] + bin_width / 2)
        for i in range(bins)
        if vol_dist[i] >= hvn_threshold and i != poc_idx
    ]

    # LVN: bins in bottom quartile with non-zero volume
    lvn_threshold = np.percentile(vol_dist[vol_dist > 0], 25) if (vol_dist > 0).any() else 0
    lvn_levels = [
        float(price_bins[i] + bin_width / 2)
        for i in range(bins)
        if 0 < vol_dist[i] <= lvn_threshold
    ]

    return VolumeProfileLevels(
        poc=poc, vah=vah, val=val,
        hvn_levels=sorted(hvn_levels),
        lvn_levels=sorted(lvn_levels),
        total_volume=total_vol,
        price_bins=price_bins,
        volume_bins=vol_dist,
    )


def nearest_hvn(spot: float, levels: VolumeProfileLevels, max_dist_pct: float = 0.005) -> Optional[float]:
    """Returns nearest HVN within max_dist_pct of spot, or None."""
    candidates = [l for l in levels.hvn_levels if abs(l - spot) / spot <= max_dist_pct]
    if not candidates:
        return None
    return min(candidates, key=lambda l: abs(l - spot))


def in_lvn(spot: float, levels: VolumeProfileLevels, bin_width_pct: float = 0.002) -> bool:
    """Returns True if spot is in a Low Volume Node (price will move fast)."""
    return any(abs(l - spot) / spot <= bin_width_pct for l in levels.lvn_levels)


class VolumeProfileStrategy(BaseStrategy):
    """
    Trade from volume profile levels (POC, VAH, VAL, HVN).

    Entry logic:
    - Price returns to POC → high probability bounce in direction of trend
    - Price breaks above VAH with volume → bullish rotation, buy the breakout
    - Price breaks below VAL → bearish rotation, sell the breakdown
    - Price at HVN → fade (mean reversion)
    - Price in LVN → momentum follow (continuation)
    """
    name = "volume_profile"
    category = "microstructure"
    preferred_regimes = ["all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        mcfg = cfg.get("microstructure", {}).get("volume_profile", {})
        self.poc_bounce_pct  = mcfg.get("poc_bounce_pct", 0.003)    # within 0.3% of POC
        self.vah_break_pct   = mcfg.get("vah_break_pct", 0.002)     # break above VAH by 0.2%
        self.val_break_pct   = mcfg.get("val_break_pct", 0.002)
        self.hvn_fade_pct    = mcfg.get("hvn_fade_pct", 0.004)
        self.lookback        = mcfg.get("lookback_bars", 60)         # session lookback
        self.bins            = mcfg.get("bins", 100)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.lookback):
            return None

        profile = compute_volume_profile(df.tail(self.lookback), bins=self.bins)
        if profile is None:
            return None

        spot = df["close"].iloc[-1]
        signals = []

        # ── POC Bounce ─────────────────────────────────────────────────────────
        poc_dist = abs(spot - profile.poc) / profile.poc
        if poc_dist <= self.poc_bounce_pct:
            trend = 1 if df["close"].iloc[-1] > df["close"].iloc[-5] else -1
            sl, tp = self._atr_stops(df, trend, atr_sl_mult=0.8, atr_tp_mult=1.5)
            signals.append(Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY if trend > 0 else SignalType.SELL,
                price=spot, stop_loss=sl, take_profit=tp,
                confidence=0.70,
                metadata={"level": "poc", "poc": round(profile.poc, 2), "dist_pct": round(poc_dist * 100, 3)},
            ))

        # ── VAH Breakout (Bullish) ─────────────────────────────────────────────
        if spot > profile.vah * (1 + self.vah_break_pct):
            prev_bar_close = df["close"].iloc[-2]
            if prev_bar_close <= profile.vah:  # fresh break
                sl, tp = self._atr_stops(df, 1, atr_sl_mult=1.0, atr_tp_mult=2.0)
                signals.append(Signal(
                    strategy=self.name, symbol=symbol,
                    signal_type=SignalType.BUY, price=spot,
                    stop_loss=sl, take_profit=tp,
                    confidence=0.68,
                    metadata={"level": "vah_break", "vah": round(profile.vah, 2)},
                ))

        # ── VAL Breakdown (Bearish) ────────────────────────────────────────────
        if spot < profile.val * (1 - self.val_break_pct):
            prev_bar_close = df["close"].iloc[-2]
            if prev_bar_close >= profile.val:
                sl, tp = self._atr_stops(df, -1, atr_sl_mult=1.0, atr_tp_mult=2.0)
                signals.append(Signal(
                    strategy=self.name, symbol=symbol,
                    signal_type=SignalType.SELL, price=spot,
                    stop_loss=sl, take_profit=tp,
                    confidence=0.68,
                    metadata={"level": "val_break", "val": round(profile.val, 2)},
                ))

        # ── HVN Fade ───────────────────────────────────────────────────────────
        hvn = nearest_hvn(spot, profile, max_dist_pct=self.hvn_fade_pct)
        if hvn:
            trend = 1 if df["close"].iloc[-1] > df["close"].iloc[-3] else -1
            fade_type = SignalType.SELL if trend > 0 else SignalType.BUY
            sl, tp = self._atr_stops(df, -trend, atr_sl_mult=0.7, atr_tp_mult=1.3)
            signals.append(Signal(
                strategy=self.name, symbol=symbol,
                signal_type=fade_type, price=spot,
                stop_loss=sl, take_profit=tp,
                confidence=0.63,
                metadata={"level": "hvn_fade", "hvn": round(hvn, 2)},
            ))

        if not signals:
            return None

        best = max(signals, key=lambda s: s.confidence)
        logger.info(
            f"VolumeProfile {symbol}: POC={profile.poc:.2f} VAH={profile.vah:.2f} VAL={profile.val:.2f} "
            f"→ {best.signal_type.value} from {best.metadata.get('level')} conf={best.confidence:.2f}"
        )
        return best
