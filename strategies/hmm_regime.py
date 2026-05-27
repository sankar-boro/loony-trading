"""
Hidden Markov Model Regime Detector.

Why HMM over ADX+vol:
- ADX is lagging (computed from past N bars) and threshold-based (arbitrary)
- HMM learns regime STRUCTURE from data — no hardcoded thresholds
- HMM gives TRANSITION PROBABILITIES: "probability we're in regime X given history"
- HMM can detect regime switches 2-3 bars early vs ADX which confirms late
- Separate model per instrument adapts to each stock's volatility personality

6 regimes (learned from data, labelled post-hoc by human):
  0: Low-vol ranging       — tight range, low volume (sleep mode)
  1: Trending up           — sustained uptrend, expanding volume
  2: Trending down         — sustained downtrend, expanding volume
  3: High-vol ranging      — choppy, two-sided, high vol (mean-reversion heaven)
  4: Breakout              — vol expansion with directional move
  5: Crash/spike           — extreme move, fat-tailed event

Features fed to HMM (all normalised):
  - Returns (log)
  - Return volatility (rolling 5-bar std)
  - Volume ratio (vs 20-bar avg)
  - ATR ratio (vs 20-bar avg ATR)
  - Up/down ratio (fraction of up closes in window)
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from strategies.regime_detector import MarketRegime
from utils.logger import get_logger

logger = get_logger("hmm_regime")

_MODEL_DIR = Path("models/hmm")
_MODEL_DIR.mkdir(parents=True, exist_ok=True)

N_STATES = 6
N_ITER   = 200
RANDOM_STATE = 42


# Map HMM state index → MarketRegime based on post-hoc labelling
# Updated after fitting by inspecting per-state means
_DEFAULT_STATE_MAP: Dict[int, MarketRegime] = {
    0: MarketRegime.LOW_VOLATILITY,
    1: MarketRegime.TRENDING_UP,
    2: MarketRegime.TRENDING_DOWN,
    3: MarketRegime.RANGING,
    4: MarketRegime.HIGH_VOLATILITY,
    5: MarketRegime.HIGH_VOLATILITY,
}


def _extract_features(df: pd.DataFrame) -> np.ndarray:
    """
    Extract 5-feature observation matrix for HMM.
    Returns shape (T, 5) float64 array.
    """
    close  = df["close"].values.astype(float)
    volume = df["volume"].values.astype(float)
    high   = df["high"].values.astype(float)
    low    = df["low"].values.astype(float)

    # Log returns
    log_ret = np.diff(np.log(close + 1e-9), prepend=np.log(close[0]))

    # Rolling 5-bar return std (realised vol proxy)
    ret_vol = pd.Series(log_ret).rolling(5, min_periods=1).std().fillna(0).values

    # Volume ratio vs 20-bar avg
    vol_avg = pd.Series(volume).rolling(20, min_periods=1).mean().fillna(volume.mean()).values
    vol_ratio = np.where(vol_avg > 0, volume / vol_avg, 1.0)

    # ATR ratio
    hl = high - low
    atr_20 = pd.Series(hl).rolling(20, min_periods=1).mean().fillna(hl.mean()).values
    atr_ratio = np.where(atr_20 > 0, hl / atr_20, 1.0)

    # Up-close ratio in rolling 5-bar window
    up = (close > np.roll(close, 1)).astype(float)
    up[0] = 0.5
    up_ratio = pd.Series(up).rolling(5, min_periods=1).mean().fillna(0.5).values

    X = np.column_stack([log_ret, ret_vol, vol_ratio, atr_ratio, up_ratio])
    # Clip extreme values to avoid HMM divergence
    X = np.clip(X, -5, 5)
    return X.astype(np.float64)


def _label_states(model: GaussianHMM) -> Dict[int, MarketRegime]:
    """
    Auto-label HMM states by inspecting per-state emission means.
    Returns state_index → MarketRegime mapping.
    """
    means = model.means_    # shape (n_states, n_features)
    # Feature indices: [log_ret, ret_vol, vol_ratio, atr_ratio, up_ratio]
    state_map: Dict[int, MarketRegime] = {}

    for i in range(N_STATES):
        ret     = means[i, 0]
        ret_vol = means[i, 1]
        vol_r   = means[i, 2]
        up_r    = means[i, 4]

        if ret_vol > 0.015:                        # very high vol
            regime = MarketRegime.HIGH_VOLATILITY
        elif ret > 0.003 and up_r > 0.6:           # consistent up-closes
            regime = MarketRegime.TRENDING_UP
        elif ret < -0.003 and up_r < 0.4:          # consistent down-closes
            regime = MarketRegime.TRENDING_DOWN
        elif ret_vol < 0.004 and vol_r < 0.8:      # low vol, low volume
            regime = MarketRegime.LOW_VOLATILITY
        else:
            regime = MarketRegime.RANGING

        state_map[i] = regime

    return state_map


class HMMRegimeDetector:
    """
    Per-instrument HMM regime detector with online prediction.

    Usage:
        detector = HMMRegimeDetector("RELIANCE")
        detector.fit(df_historical)
        regime, probs = detector.predict(df_recent)
    """

    def __init__(self, symbol: str, n_states: int = N_STATES):
        self.symbol   = symbol.upper()
        self.n_states = n_states
        self.model: Optional[GaussianHMM] = None
        self.state_map: Dict[int, MarketRegime] = dict(_DEFAULT_STATE_MAP)
        self._model_path = _MODEL_DIR / f"hmm_{self.symbol}.pkl"

    # ── Training ──────────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame, min_bars: int = 200) -> bool:
        """
        Fit HMM on historical OHLCV data.
        Returns True on success.
        """
        if len(df) < min_bars:
            logger.warning(f"HMM {self.symbol}: need {min_bars} bars, got {len(df)}")
            return False

        X = _extract_features(df)
        try:
            model = GaussianHMM(
                n_components=self.n_states,
                covariance_type="diag",
                n_iter=N_ITER,
                random_state=RANDOM_STATE,
                verbose=False,
            )
            model.fit(X)
            self.model    = model
            self.state_map = _label_states(model)
            self._save()
            logger.info(
                f"HMM {self.symbol}: fitted on {len(df)} bars, "
                f"states={[f'{i}={r.value}' for i, r in self.state_map.items()]}"
            )
            return True
        except Exception as e:
            logger.error(f"HMM {self.symbol} fit failed: {e}")
            return False

    # ── Prediction ────────────────────────────────────────────────────────────

    def predict(
        self, df: pd.DataFrame, lookback: int = 60,
    ) -> Tuple[MarketRegime, np.ndarray]:
        """
        Predict current regime from recent bars.

        Returns:
            (regime, state_probabilities)  — probs shape (n_states,)
        """
        if self.model is None:
            if not self.load():
                return MarketRegime.RANGING, np.ones(self.n_states) / self.n_states

        X = _extract_features(df.tail(lookback))
        try:
            state_seq  = self.model.predict(X)
            posteriors = self.model.predict_proba(X)   # (T, n_states)
            current_state = int(state_seq[-1])
            current_probs = posteriors[-1]              # last bar probabilities
            regime = self.state_map.get(current_state, MarketRegime.RANGING)
            return regime, current_probs
        except Exception as e:
            logger.warning(f"HMM {self.symbol} predict error: {e}")
            return MarketRegime.RANGING, np.ones(self.n_states) / self.n_states

    def predict_next_regime_probs(
        self, df: pd.DataFrame, lookback: int = 60,
    ) -> Dict[MarketRegime, float]:
        """
        Predict NEXT bar regime probabilities using transition matrix.
        π_next = π_current @ A
        This is the forward-looking edge over ADX.
        """
        if self.model is None:
            if not self.load():
                return {r: 1 / len(MarketRegime) for r in MarketRegime}

        _, current_probs = self.predict(df, lookback)
        A = self.model.transmat_                        # (n_states, n_states)
        next_probs_raw   = current_probs @ A            # (n_states,)

        # Aggregate by MarketRegime
        result: Dict[MarketRegime, float] = {}
        for i, p in enumerate(next_probs_raw):
            r = self.state_map.get(i, MarketRegime.RANGING)
            result[r] = result.get(r, 0.0) + float(p)
        return result

    def regime_confidence(self, df: pd.DataFrame, lookback: int = 60) -> float:
        """
        Returns confidence [0, 1] in the current regime prediction.
        High confidence = clear regime, low = ambiguous.
        """
        _, probs = self.predict(df, lookback)
        return float(np.max(probs))

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            with open(self._model_path, "wb") as f:
                pickle.dump({"model": self.model, "state_map": self.state_map}, f)
        except Exception as e:
            logger.warning(f"HMM save failed: {e}")

    def load(self) -> bool:
        if not self._model_path.exists():
            return False
        try:
            with open(self._model_path, "rb") as f:
                data = pickle.load(f)
            self.model    = data["model"]
            self.state_map = data["state_map"]
            return True
        except Exception as e:
            logger.warning(f"HMM load failed: {e}")
            return False

    # ── Registry ──────────────────────────────────────────────────────────────

    @staticmethod
    def list_trained() -> List[str]:
        return [p.stem.replace("hmm_", "") for p in _MODEL_DIR.glob("hmm_*.pkl")]


class HMMRegimeManager:
    """
    Manages a pool of per-symbol HMM detectors.
    Drop-in augmentation for the existing RegimeDetector.
    """

    def __init__(self, cfg: dict):
        self._cfg      = cfg
        self._detectors: Dict[str, HMMRegimeDetector] = {}

    def _get(self, symbol: str) -> HMMRegimeDetector:
        if symbol not in self._detectors:
            d = HMMRegimeDetector(symbol)
            d.load()
            self._detectors[symbol] = d
        return self._detectors[symbol]

    def detect(self, df: pd.DataFrame, symbol: str) -> MarketRegime:
        d = self._get(symbol)
        if d.model is None:
            # Fall back to ADX-based if not trained yet
            from strategies.regime_detector import RegimeDetector
            return RegimeDetector(self._cfg).detect(df)
        regime, _ = d.predict(df)
        return regime

    def detect_with_confidence(
        self, df: pd.DataFrame, symbol: str,
    ) -> Tuple[MarketRegime, float, Dict[MarketRegime, float]]:
        """Returns (regime, confidence, next_probs)."""
        d = self._get(symbol)
        if d.model is None:
            from strategies.regime_detector import RegimeDetector
            regime = RegimeDetector(self._cfg).detect(df)
            return regime, 0.5, {}
        regime, probs = d.predict(df)
        confidence    = float(np.max(probs))
        next_probs    = d.predict_next_regime_probs(df)
        return regime, confidence, next_probs

    def fit_all(self, data: Dict[str, pd.DataFrame]) -> None:
        """Fit HMM for all symbols. Called during training phase."""
        for symbol, df in data.items():
            d = self._get(symbol)
            d.fit(df)
