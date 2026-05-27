from __future__ import annotations
import pandas as pd
import numpy as np
from enum import Enum
from feature_engine.indicators import TechnicalIndicators as TI
from utils.logger import get_logger

logger = get_logger("regime")


class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


class RegimeDetector:
    """
    Classifies the current market regime using ADX, volatility, and trend alignment.
    Each strategy declares which regimes it prefers; this gating filter
    prevents applying trend strategies in chop or mean-reversion in trends.
    """

    def __init__(self, cfg: dict):
        self.adx_trend = cfg.get("regime_detection", {}).get("adx_trend_threshold", 25)
        self.adx_strong = cfg.get("regime_detection", {}).get("adx_strong_threshold", 40)
        self.vol_high = cfg.get("regime_detection", {}).get("volatility_high_pct", 0.03)
        self.vol_lb = cfg.get("regime_detection", {}).get("volatility_lookback", 20)

    def detect(self, df: pd.DataFrame) -> MarketRegime:
        if len(df) < self.vol_lb + 5:
            return MarketRegime.RANGING

        adx_vals, di_plus, di_minus = TI.adx(df)
        adx = float(adx_vals.iloc[-1])

        vol = float(df["close"].pct_change().rolling(self.vol_lb).std().iloc[-1])
        ema50 = TI.ema(df["close"], 50)
        trend_up = df["close"].iloc[-1] > ema50.iloc[-1]

        # High volatility takes precedence
        if vol > self.vol_high:
            return MarketRegime.HIGH_VOLATILITY

        if adx >= self.adx_trend:
            return MarketRegime.TRENDING_UP if trend_up else MarketRegime.TRENDING_DOWN

        if vol < self.vol_high * 0.4:
            return MarketRegime.LOW_VOLATILITY

        return MarketRegime.RANGING

    def regime_matches(self, regime: MarketRegime, preferred: list[str]) -> bool:
        if not preferred or "all" in preferred:
            return True
        regime_map = {
            "trending": [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN],
            "trending_up": [MarketRegime.TRENDING_UP],
            "trending_down": [MarketRegime.TRENDING_DOWN],
            "ranging": [MarketRegime.RANGING],
            "volatile": [MarketRegime.HIGH_VOLATILITY],
            "low_volatility": [MarketRegime.LOW_VOLATILITY],
        }
        allowed = []
        for pref in preferred:
            allowed.extend(regime_map.get(pref, []))
        return regime in allowed
