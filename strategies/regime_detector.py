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
    BREAKOUT = "breakout"          # close beyond its recent range on expanding ranges
    CRISIS = "crisis"              # extreme volatility with a sharp fall


class RegimeDetector:
    """
    Classifies the current market regime.

    Primary method: a per-symbol HMM (strategies/hmm_regime.py), used only
    if it was fitted by scripts/fit_regimes.py (or the weekly scheduler
    job), passed its out-of-sample gate and is not older than
    regime_detection.hmm_max_age_days.
    Fallback: ADX + volatility rules (always available, no training needed).

    The HMM decides calm versus turbulent (crisis, breakout, high or low
    volatility); when it says "ranging", the ADX rules decide trend versus
    range. `last_source` records which method produced the latest answer:
    "rules" (crisis check), "hmm", "hmm+adx" or "adx".
    """

    def __init__(self, cfg: dict):
        self.adx_trend = cfg.get("regime_detection", {}).get("adx_trend_threshold", 25)
        self.adx_strong = cfg.get("regime_detection", {}).get("adx_strong_threshold", 40)
        self.vol_high = cfg.get("regime_detection", {}).get("volatility_high_pct", 0.03)
        rd = cfg.get("regime_detection", {}) or {}
        self.vol_lb = rd.get("volatility_lookback", 20)
        self.use_hmm = bool(rd.get("use_hmm", True))
        self.hmm_max_age_days = float(rd.get("hmm_max_age_days", 45))
        self.breakout_lookback = int(rd.get("breakout_lookback", 20))
        self.breakout_range_mult = float(rd.get("breakout_range_mult", 1.5))
        self.crisis_vol_mult = float(rd.get("crisis_vol_mult", 2.0))
        self.crisis_drop_pct = float(rd.get("crisis_drop_pct", 0.08))
        self._hmm_cache: dict = {}   # symbol → HMMRegimeDetector or None
        self.last_source = "adx"

    def _get_hmm(self, symbol: str):
        """A usable HMMRegimeDetector for the symbol (fitted, gated, fresh), or None."""
        if symbol in self._hmm_cache:
            return self._hmm_cache[symbol]
        det = None
        try:
            from strategies.hmm_regime import HMMRegimeDetector
            cand = HMMRegimeDetector(symbol)
            if cand.load() and cand.usable(self.hmm_max_age_days):
                det = cand
        except Exception as exc:
            logger.debug("HMM load failed for %s: %s", symbol, exc)
        self._hmm_cache[symbol] = det
        return det

    def detect(self, df: pd.DataFrame, symbol: str = "") -> MarketRegime:
        # A crisis is unmistakable from the rules; never let a model miss it
        if self._is_crisis(df):
            self.last_source = "rules"
            return MarketRegime.CRISIS
        if self.use_hmm and symbol and len(df) >= 60:
            hmm = self._get_hmm(symbol)
            if hmm is not None:
                try:
                    regime, _ = hmm.predict(df)
                except Exception:
                    regime = None
                if regime is not None and regime != MarketRegime.RANGING:
                    self.last_source = "hmm"
                    return regime
                if regime is not None:
                    # The HMM separates calm from turbulent markets well but
                    # rarely finds trends from its short-window features; in a
                    # calm market the ADX rules decide trend versus range.
                    adx = self._adx_detect(df)
                    self.last_source = "hmm+adx"
                    return adx if adx in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN,
                                          MarketRegime.LOW_VOLATILITY) else MarketRegime.RANGING
        self.last_source = "adx"
        return self._adx_detect(df)

    def _is_crisis(self, df: pd.DataFrame) -> bool:
        """Volatility at crisis_vol_mult × the high-volatility line and a fall
        of crisis_drop_pct over the last five bars."""
        if len(df) < self.vol_lb + 6:
            return False
        vol = float(df["close"].pct_change().rolling(self.vol_lb).std().iloc[-1])
        drop = float(df["close"].iloc[-1] / df["close"].iloc[-6] - 1)
        return vol > self.vol_high * self.crisis_vol_mult and drop <= -self.crisis_drop_pct

    def _is_breakout(self, df: pd.DataFrame) -> bool:
        """Close beyond the prior breakout_lookback-bar range while the bar's
        range is breakout_range_mult × its average."""
        n = self.breakout_lookback
        if len(df) < n + 2 or not {"high", "low"} <= set(df.columns):
            return False
        prior = df.iloc[-(n + 1):-1]
        close = float(df["close"].iloc[-1])
        bar_range = float(df["high"].iloc[-1] - df["low"].iloc[-1])
        avg_range = float((prior["high"] - prior["low"]).mean())
        beyond = close > float(prior["high"].max()) or close < float(prior["low"].min())
        return beyond and avg_range > 0 and bar_range >= self.breakout_range_mult * avg_range

    def _adx_detect(self, df: pd.DataFrame) -> MarketRegime:
        """ADX + volatility fallback."""
        if len(df) < self.vol_lb + 5:
            return MarketRegime.RANGING

        adx_vals, _, _ = TI.adx(df)
        adx = float(adx_vals.iloc[-1])
        vol = float(df["close"].pct_change().rolling(self.vol_lb).std().iloc[-1])
        ema50 = TI.ema(df["close"], 50)
        trend_up = df["close"].iloc[-1] > ema50.iloc[-1]

        if self._is_breakout(df):
            return MarketRegime.BREAKOUT
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
        """Whether a strategy preferring `preferred` regimes may trade now.
        In a crisis only strategies that name "crisis" trade — "all" does not
        include it, so new risk stops when the market is falling apart."""
        if regime == MarketRegime.CRISIS:
            return "crisis" in (preferred or [])
        if not preferred or "all" in preferred:
            return True
        regime_map = {
            "trending": [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN, MarketRegime.BREAKOUT],
            "trending_up": [MarketRegime.TRENDING_UP],
            "trending_down": [MarketRegime.TRENDING_DOWN],
            "ranging": [MarketRegime.RANGING],
            "volatile": [MarketRegime.HIGH_VOLATILITY, MarketRegime.BREAKOUT],
            "high_volatility": [MarketRegime.HIGH_VOLATILITY],
            "low_volatility": [MarketRegime.LOW_VOLATILITY],
            "breakout": [MarketRegime.BREAKOUT],
            "crisis": [MarketRegime.CRISIS],
        }
        allowed = []
        for pref in preferred:
            allowed.extend(regime_map.get(pref, []))
        return regime in allowed
