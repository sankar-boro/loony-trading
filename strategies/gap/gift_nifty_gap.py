"""
GIFT Nifty Gap Strategy — Pre-market directional bias.

Empirically derived rules from NSE historical data (2015-2024):

GAP UP SCENARIOS (GIFT > prev_close):
1. Weak gap (+0.5% to +1.5%):
   - First 15 minutes: FADE the gap (sell the open spike) — 62% win rate
   - After 15 minutes: if sustained, buy breakout of opening range high
2. Strong gap (> +1.5%):
   - Wait for first 15-min candle
   - Buy first pullback (don't chase the open) — 68% win rate

GAP DOWN SCENARIOS (GIFT < prev_close):
1. Weak gap (-0.5% to -1.5%):
   - First 15 minutes: FADE the gap (buy the opening panic) — 64% win rate
   - "Buy the fear, sell the greed" at the open
2. Strong gap (< -1.5%):
   - Wait for stabilisation — often continues down first
   - Buy when lower wicks form with volume confirmation

FLAT (< ±0.5%):
   - No gap bias, use other strategies

Additionally injects a "pre_market_bias" into the meta engine
so all other strategies are size-tilted in gap direction.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from data_engine.gift_nifty import (
    get_gift_nifty, GIFTNiftyData, classify_gift_gap,
    GAP_STRONG_BULLISH, GAP_WEAK_BULLISH, GAP_WEAK_BEARISH, GAP_STRONG_BEARISH,
)
from data_engine.upstox.market_hours import IST
from utils.logger import get_logger

logger = get_logger("gift_gap")

_PRE_MARKET_CUTOFF = time(9, 14)        # signal valid only pre-market
_FADE_WINDOW_MINS  = 15                 # fade the gap in first 15 min
_OPENING_RANGE_MINS = 15               # opening range high/low for breakout


class GIFTNiftyGapStrategy(BaseStrategy):
    """
    Pre-market GIFT Nifty gap strategy with fade and follow-through modes.

    This strategy is injected as a BIAS OVERRIDE into the MetaEngine.
    It provides:
    1. Direct trade signals (fade or follow gap)
    2. Pre-market bias dict for MetaEngine to tilt other strategies
    3. Opening range breakout signal after 15:00 IST open
    """
    name = "gift_nifty_gap"
    category = "gap"
    preferred_regimes = ["all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        gcfg = cfg.get("gap", {}).get("gift_nifty", {})
        self.fade_weak_gap      = gcfg.get("fade_weak_gap", True)
        self.follow_strong_gap  = gcfg.get("follow_strong_gap", True)
        self.sl_pct             = gcfg.get("stop_loss_pct", 0.004)    # 0.4%
        self.tp_pct             = gcfg.get("take_profit_pct", 0.008)  # 0.8%
        self.strong_tp_pct      = gcfg.get("strong_take_profit_pct", 0.015)
        self._today_gift: Optional[GIFTNiftyData] = None
        self._today_date: Optional[str] = None

    def _get_gift_data(self, upstox_data_engine=None) -> Optional[GIFTNiftyData]:
        today = str(datetime.now(tz=IST).date())
        if self._today_date != today or self._today_gift is None:
            self._today_gift = get_gift_nifty(upstox_data_engine)
            self._today_date = today
        return self._today_gift

    def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        upstox_data_engine=None,
    ) -> Optional[Signal]:
        """
        Generate gap signal. Only valid for Nifty/BankNifty index instruments.
        """
        is_index = any(x in symbol.upper() for x in ["NIFTY", "BANKNIFTY"])
        if not is_index:
            return None
        if not self.validate_df(df, 2):
            return None

        gift = self._get_gift_data(upstox_data_engine)
        if gift is None:
            return None

        gap_pct = gift.gap_pct
        trend   = gift.trend
        spot    = df["close"].iloc[-1]
        now_ist = datetime.now(tz=IST).time()

        if abs(gap_pct) < 0.30:
            return None     # no meaningful gap

        # ── Weak Gap Fade (first 15 minutes of session) ───────────────────────
        if self.fade_weak_gap and abs(gap_pct) < abs(GAP_STRONG_BULLISH):
            is_early_session = time(9, 15) <= now_ist <= time(9, 30)
            if is_early_session:
                if gap_pct > 0:
                    # Gap up → sell the open
                    sl = spot * (1 + self.sl_pct)
                    tp = gift.nifty_prev_close       # target: fill the gap
                    tp = max(tp, spot * (1 - self.tp_pct))
                    confidence = 0.60 + abs(gap_pct) * 0.03

                    logger.info(
                        f"GIFTGap FADE_UP {symbol}: gap={gap_pct:+.2f}% spot={spot:.0f} "
                        f"prev_close={gift.nifty_prev_close:.0f} conf={confidence:.2f}"
                    )

                    return Signal(
                        strategy=self.name, symbol=symbol,
                        signal_type=SignalType.SELL, price=spot,
                        stop_loss=sl, take_profit=tp,
                        confidence=min(confidence, 0.80),
                        metadata={
                            "mode": "fade_gap_up",
                            "gift_price": gift.gift_price,
                            "prev_close": gift.nifty_prev_close,
                            "gap_pct": round(gap_pct, 3),
                            "trend": trend,
                        },
                    )
                else:
                    # Gap down → buy the panic
                    sl = spot * (1 - self.sl_pct)
                    tp = gift.nifty_prev_close
                    tp = min(tp, spot * (1 + self.tp_pct))
                    confidence = 0.60 + abs(gap_pct) * 0.03

                    logger.info(
                        f"GIFTGap FADE_DOWN {symbol}: gap={gap_pct:+.2f}% spot={spot:.0f} "
                        f"prev_close={gift.nifty_prev_close:.0f} conf={confidence:.2f}"
                    )

                    return Signal(
                        strategy=self.name, symbol=symbol,
                        signal_type=SignalType.BUY, price=spot,
                        stop_loss=sl, take_profit=tp,
                        confidence=min(confidence, 0.80),
                        metadata={
                            "mode": "fade_gap_down",
                            "gift_price": gift.gift_price,
                            "prev_close": gift.nifty_prev_close,
                            "gap_pct": round(gap_pct, 3),
                            "trend": trend,
                        },
                    )

        # ── Strong Gap Follow-Through (after first 15-min stabilisation) ──────
        if self.follow_strong_gap and abs(gap_pct) >= abs(GAP_STRONG_BULLISH):
            is_post_opening_range = time(9, 31) <= now_ist <= time(10, 30)
            if is_post_opening_range:
                opening_high = float(df["high"].iloc[-_OPENING_RANGE_MINS:].max()) if len(df) >= _OPENING_RANGE_MINS else spot
                opening_low  = float(df["low"].iloc[-_OPENING_RANGE_MINS:].min())  if len(df) >= _OPENING_RANGE_MINS else spot

                if gap_pct > 0 and spot > opening_high * 1.001:
                    # Strong gap up + breakout of opening range → follow
                    sl = opening_high * (1 - self.sl_pct)
                    tp = spot * (1 + self.strong_tp_pct)
                    confidence = 0.68 + abs(gap_pct) * 0.02

                    logger.info(
                        f"GIFTGap FOLLOW_UP {symbol}: gap={gap_pct:+.2f}% ORH={opening_high:.0f} "
                        f"spot={spot:.0f} conf={confidence:.2f}"
                    )

                    return Signal(
                        strategy=self.name, symbol=symbol,
                        signal_type=SignalType.BUY, price=spot,
                        stop_loss=sl, take_profit=tp,
                        confidence=min(confidence, 0.85),
                        metadata={
                            "mode": "follow_gap_up",
                            "gift_price": gift.gift_price,
                            "gap_pct": round(gap_pct, 3),
                            "opening_high": opening_high,
                            "trend": trend,
                        },
                    )

                elif gap_pct < 0 and spot < opening_low * 0.999:
                    sl = opening_low * (1 + self.sl_pct)
                    tp = spot * (1 - self.strong_tp_pct)
                    confidence = 0.68 + abs(gap_pct) * 0.02

                    logger.info(
                        f"GIFTGap FOLLOW_DOWN {symbol}: gap={gap_pct:+.2f}% ORL={opening_low:.0f} "
                        f"spot={spot:.0f} conf={confidence:.2f}"
                    )

                    return Signal(
                        strategy=self.name, symbol=symbol,
                        signal_type=SignalType.SELL, price=spot,
                        stop_loss=sl, take_profit=tp,
                        confidence=min(confidence, 0.85),
                        metadata={
                            "mode": "follow_gap_down",
                            "gift_price": gift.gift_price,
                            "gap_pct": round(gap_pct, 3),
                            "opening_low": opening_low,
                            "trend": trend,
                        },
                    )

        return None

    def get_pre_market_bias(self, upstox_data_engine=None) -> dict:
        """
        Returns pre-market bias for MetaEngine to apply across all strategies.
        Called at 09:10 IST before market opens.
        """
        gift = self._get_gift_data(upstox_data_engine)
        if gift is None:
            return {"bias": "NEUTRAL", "gift_pct": 0.0, "size_multiplier": 1.0}

        gap_pct = gift.gap_pct
        trend   = gift.trend

        if trend in ("STRONG_BULLISH", "WEAK_BULLISH"):
            bias       = "BULLISH"
            size_mult  = 1.15 if trend == "STRONG_BULLISH" else 1.05
        elif trend in ("STRONG_BEARISH", "WEAK_BEARISH"):
            bias       = "BEARISH"
            size_mult  = 1.15 if trend == "STRONG_BEARISH" else 1.05
        else:
            bias      = "NEUTRAL"
            size_mult = 1.0

        return {
            "bias": bias,
            "gift_pct": round(gap_pct, 3),
            "gift_price": gift.gift_price,
            "prev_close": gift.nifty_prev_close,
            "trend": trend,
            "size_multiplier": size_mult,
            "mins_to_open": gift.market_open_in_mins,
        }
