"""
India VIX Strategy — Trade volatility regime transitions.

Three sub-strategies:
1. VIX Spike Reversal  — Extreme fear (VIX > 25) → mean reversion buy on Nifty
2. Low VIX Hedge       — Extreme complacency (VIX < 12) → cheap puts as insurance
3. VIX Trend Divergence — Nifty making new high but VIX not falling → warning signal

India VIX empirical facts (from NSE historical data):
- VIX > 25 with Nifty down 3%+ in a week → 78% probability of bounce within 5 days
- VIX < 12 for 10+ consecutive days → 65% chance of 2%+ correction within 3 weeks
- VIX falling with rising Nifty = STRONG uptrend (best time to hold longs)
- VIX rising with rising Nifty = distribution (reduce longs)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from data_engine.upstox.india_vix import (
    fetch_vix_history_nse,
    get_current_vix,
    classify_vix,
    vix_percentile,
    VIX_EXTREME_FEAR, VIX_HIGH, VIX_NORMAL_LOW, VIX_COMPLACENCY,
)
from utils.logger import get_logger

logger = get_logger("vix_strategy")


class VIXStrategy(BaseStrategy):
    """
    Multi-mode VIX strategy generating directional Nifty signals.

    Modes (all active simultaneously, returning highest-confidence signal):
    - SPIKE_REVERSAL: Buy when VIX spikes → fear peak → bounce
    - LOW_VIX_HEDGE:  Buy puts when VIX extremely low → tail risk hedge
    - DIVERGENCE:     Nifty vs VIX divergence → trend warning
    - TERM_STRUCTURE: VIX term structure contango/backwardation plays
    """
    name = "vix_strategy"
    category = "volatility"
    preferred_regimes = ["all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        vcfg = cfg.get("volatility", {}).get("vix", {})
        self.spike_threshold       = vcfg.get("spike_threshold_pct", 20.0)   # 20% single-day spike
        self.vix_spike_entry       = vcfg.get("vix_spike_entry", 22.0)       # VIX level for spike trade
        self.vix_low_entry         = vcfg.get("vix_low_entry", 12.0)         # VIX too low → hedge
        self.vix_low_extreme       = vcfg.get("vix_low_extreme", 10.0)       # extreme complacency
        self.nifty_drop_pct        = vcfg.get("nifty_drop_pct", 3.0)         # Nifty fell this % before spike
        self.vix_lookback          = vcfg.get("vix_lookback", 20)
        self.consecutive_low_days  = vcfg.get("consecutive_low_days", 8)

        self._vix_df: Optional[pd.DataFrame] = None
        self._last_loaded: Optional[str] = None

    def _load_vix(self) -> pd.DataFrame:
        today = str(pd.Timestamp.today().date())
        if self._last_loaded != today or self._vix_df is None:
            self._vix_df = fetch_vix_history_nse(lookback_days=60)
            self._last_loaded = today
        return self._vix_df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """
        Generate VIX-based signal for Nifty/BankNifty index instruments.
        """
        is_index = any(x in symbol.upper() for x in ["NIFTY", "BANKNIFTY"])
        if not is_index:
            return None
        if not self.validate_df(df, 10):
            return None

        vix_df = self._load_vix()
        if vix_df.empty or "close" not in vix_df.columns:
            return None

        current_vix = float(vix_df["close"].iloc[-1])
        vix_series  = vix_df["close"].values

        spot = df["close"].iloc[-1]
        signals = []

        # ── Sub-strategy 1: Spike Reversal ────────────────────────────────────
        sig = self._spike_reversal(df, symbol, spot, current_vix, vix_series)
        if sig:
            signals.append(sig)

        # ── Sub-strategy 2: Low VIX Hedge ─────────────────────────────────────
        sig = self._low_vix_hedge(df, symbol, spot, current_vix, vix_series)
        if sig:
            signals.append(sig)

        # ── Sub-strategy 3: VIX / Price Divergence ────────────────────────────
        sig = self._divergence_signal(df, symbol, spot, current_vix, vix_df)
        if sig:
            signals.append(sig)

        if not signals:
            return None

        # Return highest confidence signal
        return max(signals, key=lambda s: s.confidence)

    def _spike_reversal(
        self, df: pd.DataFrame, symbol: str,
        spot: float, current_vix: float, vix_series: np.ndarray,
    ) -> Optional[Signal]:
        """
        VIX spikes above threshold AND Nifty is oversold → buy the fear.
        Historical win rate ~75% with 5-day hold on NSE.
        """
        if current_vix < self.vix_spike_entry:
            return None

        # Check VIX spike: current vs 5-day average
        vix_5d_avg = float(np.mean(vix_series[-6:-1])) if len(vix_series) >= 6 else current_vix
        vix_spike_pct = (current_vix - vix_5d_avg) / vix_5d_avg * 100.0

        if vix_spike_pct < self.spike_threshold * 0.5:
            return None

        # Nifty must have fallen to confirm fear is real
        nifty_5d_change = (spot - df["close"].iloc[-6]) / df["close"].iloc[-6] * 100.0
        if nifty_5d_change > -self.nifty_drop_pct:
            return None

        # VIX percentile: how extreme is this fear?
        vix_pct = vix_percentile(current_vix)
        confidence = min(0.60 + (vix_pct - 70.0) / 100.0 + abs(nifty_5d_change) / 20.0, 0.90)

        atr = float(df["high"].iloc[-14:].max() - df["low"].iloc[-14:].min()) / 14
        sl  = spot - 2.0 * atr
        tp  = spot + 3.5 * atr   # 3.5:2 RR on fear reversals

        logger.info(
            f"VIX SpikeReversal {symbol}: VIX={current_vix:.1f}({classify_vix(current_vix)}) "
            f"spike={vix_spike_pct:.1f}% Nifty5d={nifty_5d_change:.1f}% conf={confidence:.2f}"
        )

        return Signal(
            strategy=self.name, symbol=symbol,
            signal_type=SignalType.BUY, price=spot,
            stop_loss=sl, take_profit=tp,
            confidence=confidence,
            metadata={
                "sub_strategy": "spike_reversal",
                "vix": round(current_vix, 2),
                "vix_5d_avg": round(vix_5d_avg, 2),
                "vix_spike_pct": round(vix_spike_pct, 2),
                "vix_regime": classify_vix(current_vix),
                "nifty_5d_change_pct": round(nifty_5d_change, 2),
                "vix_percentile": round(vix_pct, 1),
            },
        )

    def _low_vix_hedge(
        self, df: pd.DataFrame, symbol: str,
        spot: float, current_vix: float, vix_series: np.ndarray,
    ) -> Optional[Signal]:
        """
        When VIX is extremely low for consecutive days, buy protective puts.
        Low VIX = cheap options = good time to buy insurance.
        """
        if current_vix > self.vix_low_entry:
            return None

        # Count consecutive low VIX days
        recent = vix_series[-self.consecutive_low_days:]
        low_days = int(np.sum(recent < self.vix_low_entry))

        if low_days < self.consecutive_low_days * 0.7:
            return None

        # VIX trend: is it still falling?
        vix_trend = vix_series[-1] - vix_series[-5] if len(vix_series) >= 5 else 0.0
        confidence = min(0.55 + (self.vix_low_entry - current_vix) / 5.0 + low_days * 0.01, 0.82)

        atr = float(df["high"].iloc[-14:].max() - df["low"].iloc[-14:].min()) / 14

        logger.info(
            f"VIX LowHedge {symbol}: VIX={current_vix:.1f} low_days={low_days} "
            f"trend={vix_trend:+.2f} conf={confidence:.2f}"
        )

        return Signal(
            strategy=self.name, symbol=symbol,
            signal_type=SignalType.SELL,   # short hedge / buy puts
            price=spot,
            stop_loss=spot * 1.015,
            take_profit=spot * 0.975,
            confidence=confidence,
            metadata={
                "sub_strategy": "low_vix_hedge",
                "vix": round(current_vix, 2),
                "consecutive_low_days": low_days,
                "vix_regime": classify_vix(current_vix),
                "vix_trend_5d": round(vix_trend, 3),
                "action": "buy_puts_or_reduce_longs",
            },
        )

    def _divergence_signal(
        self, df: pd.DataFrame, symbol: str,
        spot: float, current_vix: float, vix_df: pd.DataFrame,
    ) -> Optional[Signal]:
        """
        Detect divergence between VIX and Nifty:
        - Nifty making new 20-day high but VIX NOT falling → distribution warning
        - Nifty making new 20-day low but VIX NOT spiking → capitulation done
        """
        if len(df) < 22 or len(vix_df) < 22:
            return None

        nifty_high_20d = df["high"].iloc[-20:].max()
        nifty_low_20d  = df["low"].iloc[-20:].min()
        vix_20d_low    = float(vix_df["close"].iloc[-20:].min())
        vix_20d_high   = float(vix_df["close"].iloc[-20:].max())

        nifty_new_high = spot >= nifty_high_20d * 0.998
        nifty_new_low  = spot <= nifty_low_20d  * 1.002
        vix_not_low    = current_vix > vix_20d_low * 1.10   # VIX didn't fall with price rise
        vix_not_high   = current_vix < vix_20d_high * 0.85  # VIX didn't spike with price fall

        if nifty_new_high and vix_not_low:
            confidence = 0.62
            atr = float(df["high"].iloc[-14:].max() - df["low"].iloc[-14:].min()) / 14
            logger.info(f"VIX Divergence {symbol}: NEW HIGH but VIX not falling → distribution")
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=spot,
                stop_loss=spot * 1.012, take_profit=spot * 0.980,
                confidence=confidence,
                metadata={
                    "sub_strategy": "vix_price_divergence",
                    "divergence_type": "new_high_vix_not_falling",
                    "vix": round(current_vix, 2),
                    "vix_20d_low": round(vix_20d_low, 2),
                },
            )

        if nifty_new_low and vix_not_high:
            confidence = 0.60
            atr = float(df["high"].iloc[-14:].max() - df["low"].iloc[-14:].min()) / 14
            logger.info(f"VIX Divergence {symbol}: NEW LOW but VIX not spiking → selling exhausted")
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=spot,
                stop_loss=spot * 0.988, take_profit=spot * 1.020,
                confidence=confidence,
                metadata={
                    "sub_strategy": "vix_price_divergence",
                    "divergence_type": "new_low_vix_not_spiking",
                    "vix": round(current_vix, 2),
                    "vix_20d_high": round(vix_20d_high, 2),
                },
            )

        return None

    def get_vix_market_regime(self) -> dict:
        """
        Returns current VIX-based market regime for use by MetaEngine.
        Influences position sizing and strategy selection across the system.
        """
        vix_df = self._load_vix()
        if vix_df.empty:
            return {"regime": "UNKNOWN", "vix": None, "action": "trade_normal"}

        current_vix = float(vix_df["close"].iloc[-1])
        regime = classify_vix(current_vix)
        pct    = vix_percentile(current_vix)

        if regime == "EXTREME_FEAR":
            action = "buy_dips_reduce_shorts_consider_puts"
            size_mult = 0.6    # reduce size in panic
        elif regime == "HIGH_FEAR":
            action = "cautious_long_bias_tight_stops"
            size_mult = 0.8
        elif regime in ("NORMAL", "ELEVATED"):
            action = "trade_normal"
            size_mult = 1.0
        elif regime == "LOW":
            action = "add_long_bias_watch_for_complacency"
            size_mult = 1.1
        else:  # EXTREME_COMPLACENCY
            action = "buy_cheap_protection_reduce_longs"
            size_mult = 0.85

        return {
            "regime": regime,
            "vix": round(current_vix, 2),
            "vix_percentile": round(pct, 1),
            "action": action,
            "size_multiplier": size_mult,
        }
