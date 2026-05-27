import numpy as np
from typing import List
from .base_model import BaseMLModel
from utils.logger import get_logger

logger = get_logger("ensemble")


class EnsembleModel(BaseMLModel):
    """
    Soft-voting ensemble of multiple ML models.
    Weights can be set based on out-of-sample performance.
    """
    name = "ensemble"

    def __init__(self, models: List[BaseMLModel], weights: List[float] | None = None):
        self.models = models
        self.weights = weights or [1.0] * len(models)
        self.is_trained = all(m.is_trained for m in models)
        self.model_dir = models[0].model_dir if models else None

    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        for m in self.models:
            m.train(X, y)
        self.is_trained = True

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.argmax(self.predict_proba(X), axis=1)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        total_weight = sum(self.weights)
        proba_sum = None
        for model, w in zip(self.models, self.weights):
            if not model.is_trained:
                continue
            try:
                p = model.predict_proba(X)
                proba_sum = p * (w / total_weight) if proba_sum is None else proba_sum + p * (w / total_weight)
            except Exception as e:
                logger.warning(f"Ensemble model {model.name} predict failed: {e}")
        if proba_sum is None:
            return np.array([[0.0, 1.0, 0.0]])
        return proba_sum

    def update_weights_by_accuracy(self, X_val: np.ndarray, y_val: np.ndarray) -> None:
        accs = []
        for m in self.models:
            if m.is_trained:
                preds = m.predict(X_val)
                accs.append(float(np.mean(preds == y_val)))
            else:
                accs.append(0.0)
        total = sum(accs)
        self.weights = [a / total if total > 0 else 1.0 / len(accs) for a in accs]
        logger.info(f"Ensemble weights updated: {dict(zip([m.name for m in self.models], self.weights))}")
