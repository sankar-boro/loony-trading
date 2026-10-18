import pandas as pd
import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from ml_models.dataset import build_features, feature_columns, feature_row
from utils.logger import get_logger

logger = get_logger("ml_strategy")


def _trained_columns(model) -> list[str]:
    """Feature columns the model was trained on (ensemble or its first member)."""
    cols = getattr(model, "feature_cols", None)
    if not cols:
        members = getattr(model, "models", None) or []
        cols = getattr(members[0], "feature_cols", None) if members else None
    return list(cols or [])


class MLClassifierStrategy(BaseStrategy):
    """
    Wraps ML model (XGBoost/LightGBM/LSTM) as a strategy.
    Model predicts: 1 (buy), -1 (sell), 0 (hold).
    """
    name = "ml_classifier"
    category = "ml"
    preferred_regimes = ["all"]

    def __init__(self, cfg: dict, model=None):
        super().__init__(cfg)
        self.model = model
        self._warned: set[str] = set()
        self.min_confidence = self.param("ml_min_confidence", 0.6)

    def set_model(self, model) -> None:
        self.model = model
        self._warned.clear()

    def _warn_once(self, key: str, msg: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(msg)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if self.model is None or not self.validate_df(df, 60):
            return None

        try:
            # Use exactly the columns, in the order, the model was trained on.
            cols = _trained_columns(self.model)
            if not cols:
                self._warn_once("no_cols", "ML model has no saved feature columns — retrain with "
                                           "scripts/train_ml.py; using current feature set")
                cols = feature_columns(build_features(df))
            X = feature_row(df, cols)
            if X is None:
                return None

            if hasattr(self.model, "predict_proba"):
                proba = self.model.predict_proba(X)[0]
                pred_class = np.argmax(proba)
                confidence = float(proba[pred_class])
                # Expect classes: 0=sell, 1=hold, 2=buy
                direction_map = {0: -1, 1: 0, 2: 1}
                direction = direction_map.get(pred_class, 0)
            else:
                pred = self.model.predict(X)[0]
                direction = int(pred)
                confidence = 0.7

            if confidence < self.min_confidence or direction == 0:
                return None

            price = df["close"].iloc[-1]
            sl, tp = self._atr_stops(df, direction)
            sig_type = SignalType.BUY if direction == 1 else SignalType.SELL

            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=sig_type, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=confidence,
                metadata={"model": type(self.model).__name__},
            )
        except Exception as e:
            self._warn_once(type(e).__name__, f"ML prediction failed for {symbol}: {e}")
            return None
