from __future__ import annotations
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Tuple


class BaseMLModel(ABC):
    name: str = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = None
        self.feature_cols: list[str] = []
        self.is_trained = False
        self.model_dir = Path(__file__).resolve().parent.parent / "models"
        self.model_dir.mkdir(exist_ok=True)

    @abstractmethod
    def train(self, X: np.ndarray, y: np.ndarray) -> None: ...

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray: ...

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        # Default: one-hot from discrete prediction
        preds = self.predict(X)
        result = np.zeros((len(preds), 3))
        for i, p in enumerate(preds):
            result[i, int(p) + 1] = 1.0
        return result

    def save(self) -> None:
        path = self.model_dir / f"{self.name}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "feature_cols": self.feature_cols}, f)

    def load(self) -> bool:
        path = self.model_dir / f"{self.name}.pkl"
        if not path.exists():
            return False
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.model = data["model"]
        self.feature_cols = data["feature_cols"]
        self.is_trained = True
        return True

    @staticmethod
    def make_labels(df: pd.DataFrame, forward_bars: int = 5,
                     threshold: float = 0.005) -> np.ndarray:
        """Generate 3-class labels: 0=sell, 1=hold, 2=buy."""
        future_return = df["close"].shift(-forward_bars) / df["close"] - 1
        labels = np.where(future_return > threshold, 2,
                          np.where(future_return < -threshold, 0, 1))
        return labels

    @staticmethod
    def train_test_split_time(X: np.ndarray, y: np.ndarray,
                               test_ratio: float = 0.2) -> Tuple:
        split = int(len(X) * (1 - test_ratio))
        return X[:split], X[split:], y[:split], y[split:]
