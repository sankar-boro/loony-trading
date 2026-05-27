import pandas as pd
import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.feature_builder import FeatureBuilder


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
        self.feature_builder = FeatureBuilder()
        self.min_confidence = cfg.get("ml_min_confidence", 0.6)

    def set_model(self, model) -> None:
        self.model = model

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if self.model is None or not self.validate_df(df, 60):
            return None

        try:
            features = self.feature_builder.build(df)
            if features.empty:
                return None

            feature_cols = [c for c in features.columns
                            if c not in ("open", "high", "low", "close", "volume")]
            X = features[feature_cols].iloc[-1:].values

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
            return None
