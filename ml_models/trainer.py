import numpy as np
import pandas as pd
from typing import List
from feature_engine.feature_builder import FeatureBuilder
from .base_model import BaseMLModel
from .xgb_model import XGBoostModel
from .lgbm_model import LightGBMModel
from .lstm_model import LSTMModel
from .ensemble import EnsembleModel
from utils.logger import get_logger

logger = get_logger("trainer")


class ModelTrainer:
    """
    Orchestrates feature extraction, label generation, training, and periodic retraining.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.feature_builder = FeatureBuilder()
        self.forward_bars = cfg.get("ml", {}).get("forward_bars", 5)
        self.threshold = cfg.get("ml", {}).get("label_threshold", 0.005)
        self._exclude_cols = {"open", "high", "low", "close", "volume"}

    def prepare_data(self, df: pd.DataFrame):
        features = self.feature_builder.build(df)
        labels = BaseMLModel.make_labels(features, self.forward_bars, self.threshold)
        feature_cols = [c for c in features.columns if c not in self._exclude_cols]
        X = features[feature_cols].values
        y = labels
        # Drop NaN rows
        valid = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
        return X[valid], y[valid].astype(int), feature_cols

    def train_all(self, df: pd.DataFrame) -> EnsembleModel:
        X, y, feature_cols = self.prepare_data(df)
        if len(X) < 200:
            logger.warning("Insufficient data for training")
            return None

        logger.info(f"Training on {len(X)} samples with {len(feature_cols)} features")

        models: List[BaseMLModel] = [
            XGBoostModel(self.cfg),
            LightGBMModel(self.cfg),
        ]

        # LSTM only if we have enough data
        if len(X) > 500:
            lstm = LSTMModel(self.cfg)
            lstm.feature_cols = feature_cols
            models.append(lstm)

        for m in models:
            m.feature_cols = feature_cols
            m.train(X, y)
            m.save()

        ensemble = EnsembleModel(models)
        split = int(len(X) * 0.8)
        if split < len(X):
            ensemble.update_weights_by_accuracy(X[split:], y[split:])

        return ensemble

    def get_feature_matrix(self, df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
        features = self.feature_builder.build(df)
        feature_cols = [c for c in features.columns if c not in self._exclude_cols]
        X = features[feature_cols].values
        return X, feature_cols
