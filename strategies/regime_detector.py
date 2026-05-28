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
    Classifies the current market regime.

    Primary method: HMM (per-symbol, fitted on historical data).
    Fallback: ADX + volatility rules (always available, no training needed).

    HMM is preferred because it:
    - Detects regime switches 2-3 bars earlier than ADX
    - Provides transition probabilities (forward-looking)
    - Adapts per-instrument to each stock's volatility personality
    """

    def __init__(self, cfg: dict):
        self.adx_trend = cfg.get("regime_detection", {}).get("adx_trend_threshold", 25)
        self.adx_strong = cfg.get("regime_detection", {}).get("adx_strong_threshold", 40)
        self.vol_high = cfg.get("regime_detection", {}).get("volatility_high_pct", 0.03)
        self.vol_lb = cfg.get("regime_detection", {}).get("volatility_lookback", 20)
        self._hmm_cache: dict = {}   # symbol → HMMRegimeDetector

    def _get_hmm(self, symbol: str):
        """Return a loaded (or freshly fitted) HMMRegimeDetector, or None."""
        if symbol in self._hmm_cache:
            return self._hmm_cache[symbol]
        try:
            from strategies.hmm_regime import HMMRegimeDetector
            det = HMMRegimeDetector(symbol)
            if det.load():
                self._hmm_cache[symbol] = det
                return det
        except Exception:
            pass
        return None

    def detect(self, df: pd.DataFrame, symbol: str = "") -> MarketRegime:
        # Try HMM first if symbol provided and model exists
        if symbol and len(df) >= 60:
            hmm = self._get_hmm(symbol)
            if hmm is not None:
                try:
                    regime, _ = hmm.predict(df)
                    return regime
                except Exception:
                    pass

        return self._adx_detect(df)

    def _adx_detect(self, df: pd.DataFrame) -> MarketRegime:
        """ADX + volatility fallback."""
        if len(df) < self.vol_lb + 5:
            return MarketRegime.RANGING

        adx_vals, _, _ = TI.adx(df)
        adx = float(adx_vals.iloc[-1])
        vol = float(df["close"].pct_change().rolling(self.vol_lb).std().iloc[-1])
        ema50 = TI.ema(df["close"], 50)
        trend_up = df["close"].iloc[-1] > ema50.iloc[-1]

        if vol > self.vol_high:
            return MarketRegime.HIGH_VOLATILITY
        if adx >= self.adx_trend:
            return MarketRegime.TRENDING_UP if trend_up else MarketRegime.TRENDING_DOWN
        if vol < self.vol_high * 0.4:
            return MarketRegime.LOW_VOLATILITY
        return MarketRegime.RANGING

    def fit_hmm(self, symbol: str, df: pd.DataFrame) -> bool:
        """
        Fit and save an HMM model for the given symbol.
        Call once per symbol during training/warm-up.
        Returns True on success.
        """
        try:
            from strategies.hmm_regime import HMMRegimeDetector
            det = HMMRegimeDetector(symbol)
            ok  = det.fit(df)
            if ok:
                self._hmm_cache[symbol] = det
            return ok
        except Exception as exc:
            logger.warning("HMM fit failed for %s: %s", symbol, exc)
            return False

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
