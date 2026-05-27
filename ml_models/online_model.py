"""
Online / Incremental Learning with Concept Drift Detection.

Why online learning:
- Markets change intraday — a model trained last night may already be stale
- Batch retraining every night is slow and misses regime shifts mid-session
- Online models update after EVERY prediction, continuously adapting

Concept drift:
- Statistical change in data distribution (e.g., market opens flat, then
  a macro shock hits at 12:00 — signal distribution shifts completely)
- ADWIN (Adaptive Windowing): detects drift by testing if two halves of a
  rolling window have significantly different mean accuracy
- Page-Hinkley: simpler sequential change-point test

Components:
1. OnlineEnsemble   — wraps River's streaming ML models
2. DriftDetector    — ADWIN + Page-Hinkley combined
3. AdaptiveModel    — auto-retrains batch model when drift detected
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from utils.logger import get_logger

logger = get_logger("online_model")


# ── Drift Detectors ────────────────────────────────────────────────────────────

@dataclass
class ADWINDetector:
    """
    ADWIN (Adaptive Windowing) concept drift detector.
    Maintains a window of values and detects when the mean has shifted.
    O(log n) per update.
    """
    delta: float = 0.002        # confidence parameter (lower = more sensitive)
    _window: List[float] = field(default_factory=list)
    drift_detected: bool = False

    def update(self, value: float) -> bool:
        """Add a value, return True if drift detected."""
        self._window.append(value)
        self.drift_detected = False

        # ADWIN: test if any split point shows significant mean difference
        n = len(self._window)
        if n < 10:
            return False

        total_sum = sum(self._window)
        total_n   = n

        cum_sum = 0.0
        for i in range(1, n):
            cum_sum += self._window[i - 1]
            n0  = i
            n1  = total_n - i
            mu0 = cum_sum / n0
            mu1 = (total_sum - cum_sum) / n1
            bound = np.sqrt(0.5 / min(n0, n1) * np.log(4 * total_n / self.delta))
            if abs(mu0 - mu1) >= bound:
                # Drift detected — shrink window to most recent half
                self._window = self._window[i:]
                self.drift_detected = True
                return True

        # Limit window size to prevent memory growth
        if len(self._window) > 1000:
            self._window = self._window[-500:]

        return False

    def reset(self) -> None:
        self._window.clear()
        self.drift_detected = False


@dataclass
class PageHinkleyDetector:
    """
    Page-Hinkley change-point test.
    Detects when cumulative sum of deviations from running mean exceeds threshold.
    """
    threshold: float = 50.0     # detection threshold λ
    alpha:     float = 0.005    # forgetting factor for running mean
    _cum_sum:  float = 0.0
    _running_mean: float = 0.0
    _n:        int   = 0
    drift_detected: bool = False

    def update(self, value: float) -> bool:
        self._n += 1
        self._running_mean += (value - self._running_mean) * self.alpha
        self._cum_sum = max(0.0, self._cum_sum + (self._running_mean - value - self.alpha))
        self.drift_detected = self._cum_sum > self.threshold
        if self.drift_detected:
            self.reset()
            return True   # return before reset clears drift_detected
        return self.drift_detected

    def reset(self) -> None:
        self._cum_sum      = 0.0
        self._running_mean = 0.0
        self._n            = 0
        self.drift_detected = False


# ── Online Ensemble ────────────────────────────────────────────────────────────

class OnlineEnsemble:
    """
    Streaming ensemble using River's Hoeffding Tree + Naive Bayes.
    Falls back to numpy-only implementation if River is unavailable.
    """

    def __init__(self, n_classes: int = 3):
        self.n_classes   = n_classes
        self._use_river  = False
        self._models     = []
        self._weights    = []
        self._n_correct  = 0
        self._n_total    = 0
        self._init_models()

    def _init_models(self) -> None:
        try:
            from river.tree import HoeffdingAdaptiveTreeClassifier
            from river.naive_bayes import GaussianNB
            from river.linear_model import LogisticRegression
            from river import optim, preprocessing

            self._models = [
                HoeffdingAdaptiveTreeClassifier(grace_period=50, delta=1e-5),
                GaussianNB(),
                LogisticRegression(optimizer=optim.SGD(lr=0.01)),
            ]
            self._weights = [1.0 / 3] * 3
            self._use_river = True
            logger.info("OnlineEnsemble: using River (Hoeffding + GaussNB + LogReg)")
        except ImportError:
            logger.warning("River not available — using simple online Perceptron fallback")
            self._init_fallback()

    def _init_fallback(self) -> None:
        """Numpy-only fallback: online perceptron."""
        self._weights_w: Optional[np.ndarray] = None
        self._bias: float = 0.0
        self._lr: float   = 0.01
        self._use_river   = False

    def learn_one(self, x: Dict[str, float], y: int) -> None:
        """Update all models with one labelled sample."""
        if self._use_river:
            for i, model in enumerate(self._models):
                try:
                    pred = model.predict_one(x)
                    correct = 1.0 if pred == y else 0.0
                    # Update weight (exponential moving accuracy)
                    self._weights[i] = 0.9 * self._weights[i] + 0.1 * correct
                    model.learn_one(x, y)
                except Exception:
                    pass
            total = sum(self._weights) + 1e-9
            self._weights = [w / total for w in self._weights]
        else:
            x_arr = np.array(list(x.values()), dtype=float)
            if self._weights_w is None:
                self._weights_w = np.zeros(len(x_arr) * self.n_classes)
            # Simple one-vs-rest update
            for c in range(self.n_classes):
                start = c * len(x_arr)
                end   = start + len(x_arr)
                pred  = np.dot(x_arr, self._weights_w[start:end]) + self._bias
                label = 1.0 if y == c else -1.0
                if pred * label <= 0:
                    self._weights_w[start:end] += self._lr * label * x_arr
                    self._bias += self._lr * label

    def predict_proba_one(self, x: Dict[str, float]) -> np.ndarray:
        """Predict class probabilities for one sample."""
        if self._use_river:
            proba_sum = np.zeros(self.n_classes)
            for model, w in zip(self._models, self._weights):
                try:
                    p = model.predict_proba_one(x)
                    for c in range(self.n_classes):
                        proba_sum[c] += w * p.get(c, 1 / self.n_classes)
                except Exception:
                    proba_sum += w / self.n_classes
            total = proba_sum.sum()
            return proba_sum / total if total > 0 else np.ones(self.n_classes) / self.n_classes
        else:
            # Fallback: softmax over linear scores
            x_arr = np.array(list(x.values()), dtype=float)
            if self._weights_w is None:
                return np.ones(self.n_classes) / self.n_classes
            scores = np.array([
                np.dot(x_arr, self._weights_w[c * len(x_arr): (c + 1) * len(x_arr)])
                for c in range(self.n_classes)
            ])
            scores -= scores.max()
            exp_s = np.exp(scores)
            return exp_s / exp_s.sum()

    def predict_one(self, x: Dict[str, float]) -> int:
        return int(np.argmax(self.predict_proba_one(x)))

    @property
    def rolling_accuracy(self) -> float:
        if self._n_total == 0:
            return 0.5
        return self._n_correct / self._n_total


class AdaptiveModel:
    """
    Wraps a batch ML model (e.g. XGBoost) + online model for continuous adaptation.

    Strategy:
    - Batch model provides base predictions (trained nightly)
    - Online model adapts intraday (updates after each bar)
    - Drift detector monitors online model accuracy
    - If drift detected → flag for overnight batch retrain
    - Final prediction = weighted blend (batch * alpha + online * (1-alpha))
    """

    def __init__(
        self,
        batch_model=None,
        n_classes: int = 3,
        online_weight: float = 0.3,     # weight given to online model
        drift_threshold: float = 50.0,
    ):
        self.batch_model    = batch_model
        self.online_model   = OnlineEnsemble(n_classes)
        self.adwin          = ADWINDetector(delta=0.002)
        self.page_hinkley   = PageHinkleyDetector(threshold=drift_threshold)
        self.online_weight  = online_weight
        self.n_classes      = n_classes

        self._accuracy_window: Deque[float] = deque(maxlen=100)
        self.drift_flag: bool   = False
        self.drift_count: int   = 0
        self.last_drift_ts: Optional[float] = None

    def predict_proba(self, x_arr: np.ndarray, x_dict: Optional[Dict] = None) -> np.ndarray:
        """
        Blended prediction: batch + online.
        x_arr: numpy array for batch model
        x_dict: dict for online model (if None, convert from x_arr)
        """
        if x_dict is None:
            x_dict = {f"f{i}": float(v) for i, v in enumerate(x_arr.flatten())}

        # Batch model prediction
        batch_proba = np.ones(self.n_classes) / self.n_classes
        if self.batch_model is not None and getattr(self.batch_model, "is_trained", False):
            try:
                batch_proba = self.batch_model.predict_proba(x_arr.reshape(1, -1))[0]
            except Exception:
                pass

        # Online model prediction
        online_proba = self.online_model.predict_proba_one(x_dict)

        # Blend
        alpha = 1.0 - self.online_weight
        blended = alpha * batch_proba + self.online_weight * online_proba
        return blended / blended.sum()

    def update(self, x_arr: np.ndarray, true_label: int, x_dict: Optional[Dict] = None) -> bool:
        """
        Update online model with confirmed label.
        Returns True if drift was detected.
        """
        if x_dict is None:
            x_dict = {f"f{i}": float(v) for i, v in enumerate(x_arr.flatten())}

        # Check accuracy before updating
        proba   = self.online_model.predict_proba_one(x_dict)
        pred    = int(np.argmax(proba))
        correct = float(pred == true_label)
        self._accuracy_window.append(correct)

        # Feed accuracy to drift detectors
        adwin_drift = self.adwin.update(correct)
        ph_drift    = self.page_hinkley.update(correct)
        drift = adwin_drift or ph_drift

        if drift:
            self.drift_flag  = True
            self.drift_count += 1
            self.last_drift_ts = time.time()
            logger.warning(
                f"Concept drift detected! ADWIN={adwin_drift} PH={ph_drift} "
                f"count={self.drift_count} acc_30={self.recent_accuracy(30):.2%}"
            )

        # Update online model
        self.online_model.learn_one(x_dict, true_label)
        return drift

    def clear_drift_flag(self) -> None:
        self.drift_flag = False

    def recent_accuracy(self, n: int = 20) -> float:
        if not self._accuracy_window:
            return 0.5
        recent = list(self._accuracy_window)[-n:]
        return float(np.mean(recent))

    def should_retrain(self, min_accuracy: float = 0.45) -> bool:
        """Returns True if model should be retrained (poor accuracy + drift)."""
        return self.drift_flag and self.recent_accuracy(50) < min_accuracy

    def status(self) -> dict:
        return {
            "drift_detected":  self.drift_flag,
            "drift_count":     self.drift_count,
            "recent_acc_20":   round(self.recent_accuracy(20), 4),
            "recent_acc_50":   round(self.recent_accuracy(50), 4),
            "online_weight":   self.online_weight,
            "should_retrain":  self.should_retrain(),
        }
