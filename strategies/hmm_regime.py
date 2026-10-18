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

import pickle
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from strategies.regime_detector import MarketRegime
from utils.logger import get_logger

logger = get_logger("hmm_regime")

_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "hmm"

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
    vol_ratio = np.divide(volume, vol_avg, out=np.ones_like(volume), where=vol_avg > 0)

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


class _Scaler:
    """Per-feature standardisation. Raw features differ hugely in scale
    (return variance ~1e-4 against hmmlearn's 1e-3 variance floor), and a
    constant feature — volume on an index — has zero variance; both break
    the fit. Labels are read from de-standardised state means."""

    def __init__(self, X: np.ndarray):
        self.mu = X.mean(axis=0)
        self.sd = np.where(X.std(axis=0) > 1e-9, X.std(axis=0), 1.0)

    def __call__(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mu) / self.sd

    def raw_means(self, model: GaussianHMM) -> np.ndarray:
        return model.means_ * self.sd + self.mu


def _label_states(model: GaussianHMM, X: Optional[np.ndarray] = None,
                  means: Optional[np.ndarray] = None) -> Dict[int, MarketRegime]:
    """
    Auto-label HMM states from their emission means, relative to the
    symbol's own feature distribution `X` (median volatility, spread of
    returns), so the same rules work for a calm index, a volatile small cap
    and intraday bars. Without X, daily-scale defaults are used.
    """
    means = model.means_ if means is None else means    # (n_states, n_features), raw scale
    # Feature indices: [log_ret, ret_vol, vol_ratio, atr_ratio, up_ratio]
    # "Normal" volatility: the 35th percentile rather than the median, so a
    # symbol that is turbulent half the time still has a calm baseline.
    med_vol = float(np.percentile(X[:, 1], 35)) if X is not None else 0.008
    ret_sd = float(np.std(X[:, 0])) if X is not None else 0.012
    state_map: Dict[int, MarketRegime] = {}
    for i in range(model.n_components):
        ret, ret_vol, _vol_r, atr_r, up_r = (float(v) for v in means[i, :5])
        if ret_vol > 3.0 * med_vol and ret < -0.5 * ret_sd:
            regime = MarketRegime.CRISIS
        elif atr_r > 1.3 and abs(ret) > 0.3 * ret_sd:
            regime = MarketRegime.BREAKOUT
        elif ret_vol > 2.0 * med_vol:
            regime = MarketRegime.HIGH_VOLATILITY
        elif ret > 0.15 * ret_sd and up_r > 0.55:
            regime = MarketRegime.TRENDING_UP
        elif ret < -0.15 * ret_sd and up_r < 0.45:
            regime = MarketRegime.TRENDING_DOWN
        elif ret_vol < 0.6 * med_vol:
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
        self.meta: dict = {}
        self.scaler: Optional[_Scaler] = None

    @property
    def _model_path(self) -> Path:
        return _MODEL_DIR / f"hmm_{self.symbol}.pkl"

    # ── Training ──────────────────────────────────────────────────────────────

    def _new_model(self, n_states: int) -> GaussianHMM:
        return GaussianHMM(n_components=n_states, covariance_type="diag",
                           n_iter=N_ITER, random_state=RANDOM_STATE, verbose=False)

    def evaluate(self, df: pd.DataFrame, holdout: float = 0.25,
                 min_mean_run: float = 3.0, min_r2: float = 0.05, horizon: int = 5) -> dict:
        """Out-of-sample gate. Fit on the first (1 − holdout) of the bars and
        test on the rest:

        - the regime must predict the next `horizon` bars' realised volatility:
          each state's average forward volatility (learned on the training
          bars) must explain at least `min_r2` of its variance on the test
          bars. Volatility clusters in real markets; in pure noise it does not,
          and a model that only reflects its own rolling features fails here;
        - regimes must last at least `min_mean_run` bars on average on the
          test bars, not flip every bar.

        The per-bar log-likelihood against a one-state model is reported too.
        """
        X = _extract_features(df)
        split = int(len(X) * (1 - holdout))
        try:
            scaler = _Scaler(X[:split])
            train, test = scaler(X[:split]), scaler(X[split:])
            hmm = self._new_model(self.n_states).fit(train)
            base = self._new_model(1).fit(train)
            ll_hmm = float(hmm.score(test)) / len(test)
            ll_base = float(base.score(test)) / len(test)
            s_train, s_test = hmm.predict(train), hmm.predict(test)
        except Exception as exc:
            return {"passed": False, "reason": f"fit failed: {exc}", "test_bars": len(X) - split}

        # Realised volatility of the next `horizon` log returns, per bar
        ret = X[:, 0]
        fwd = np.full(len(ret), np.nan)
        for t in range(len(ret) - horizon):
            fwd[t] = np.std(ret[t + 1:t + 1 + horizon])
        f_train, f_test = fwd[:split], fwd[split:]
        overall = float(np.nanmean(f_train))
        state_vol = {k: float(np.nanmean(f_train[s_train == k]))
                     for k in np.unique(s_train) if np.any(~np.isnan(f_train[s_train == k]))}
        pred = np.array([state_vol.get(k, overall) for k in s_test])
        ok = ~np.isnan(f_test)
        sst = float(np.sum((f_test[ok] - overall) ** 2))
        r2 = 1 - float(np.sum((f_test[ok] - pred[ok]) ** 2)) / sst if sst > 0 else 0.0

        runs = 1 + int(np.sum(s_test[1:] != s_test[:-1]))
        mean_run = len(s_test) / runs
        passed = r2 >= min_r2 and mean_run >= min_mean_run
        reason = ("" if passed else
                  f"regime does not predict volatility (R² {r2:.2f})" if r2 < min_r2 else
                  f"regimes too short ({mean_run:.1f} bars)")
        return {"ll_hmm": round(ll_hmm, 4), "ll_base": round(ll_base, 4), "vol_r2": round(r2, 3),
                "mean_run": round(mean_run, 2), "test_bars": len(test),
                "passed": passed, "reason": reason}

    def fit(self, df: pd.DataFrame, min_bars: int = 200, gate: bool = True) -> bool:
        """Fit on historical OHLCV bars and save. With `gate`, the model is
        first checked out of sample (evaluate) and saved as unusable if it
        fails, so RegimeDetector keeps using the ADX rules. Returns True if
        the saved model passed."""
        if len(df) < min_bars:
            logger.warning(f"HMM {self.symbol}: need {min_bars} bars, got {len(df)}")
            return False
        try:
            gate_result = self.evaluate(df) if gate else {"passed": True, "reason": ""}
            X = _extract_features(df)
            scaler = _Scaler(X)
            model = self._new_model(self.n_states).fit(scaler(X))
            if not np.all(np.isfinite(model.means_)):
                raise ValueError("fit diverged (non-finite state means)")
            self.model = model
            self.scaler = scaler
            self.state_map = _label_states(model, X, scaler.raw_means(model))
            self.meta = {**gate_result, "fitted_at": time.time(), "n_bars": len(df)}
            self._save()
            logger.info(
                f"HMM {self.symbol}: fitted on {len(df)} bars, gate "
                f"{'passed' if gate_result['passed'] else 'FAILED: ' + gate_result['reason']}, "
                f"states={[f'{i}={r.value}' for i, r in self.state_map.items()]}")
            return bool(gate_result["passed"])
        except Exception as e:
            logger.error(f"HMM {self.symbol} fit failed: {e}")
            self.meta = {"passed": False, "reason": f"fit failed: {e}", "fitted_at": time.time(),
                         "n_bars": len(df)}
            return False

    def usable(self, max_age_days: float = 45) -> bool:
        """Loaded, passed its gate, and fitted within max_age_days."""
        if self.model is None or not self.meta.get("passed"):
            return False
        return time.time() - float(self.meta.get("fitted_at", 0)) <= max_age_days * 86400

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
        if self.scaler is not None:
            X = self.scaler(X)
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
            _MODEL_DIR.mkdir(parents=True, exist_ok=True)
            with open(self._model_path, "wb") as f:
                pickle.dump({"model": self.model, "state_map": self.state_map,
                             "meta": self.meta, "scaler": self.scaler}, f)
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
            self.meta      = data.get("meta", {})    # models saved before the gate have none
            self.scaler    = data.get("scaler")
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
