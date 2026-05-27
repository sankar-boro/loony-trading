import numpy as np
from .base_model import BaseMLModel
from utils.logger import get_logger

logger = get_logger("xgb_model")


class XGBoostModel(BaseMLModel):
    name = "xgboost"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        xgb_cfg = cfg.get("ml", {}).get("xgboost", {})
        self.n_estimators = xgb_cfg.get("n_estimators", 300)
        self.max_depth = xgb_cfg.get("max_depth", 6)
        self.learning_rate = xgb_cfg.get("learning_rate", 0.05)

    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        try:
            from xgboost import XGBClassifier
        except ImportError:
            logger.error("xgboost not installed: pip install xgboost")
            return

        X_tr, X_te, y_tr, y_te = self.train_test_split_time(X, y)
        self.model = XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            use_label_encoder=False,
            eval_metric="mlogloss",
            random_state=42,
        )
        self.model.fit(
            X_tr, y_tr,
            eval_set=[(X_te, y_te)],
            early_stopping_rounds=20,
            verbose=False,
        )
        self.is_trained = True
        acc = np.mean(self.model.predict(X_te) == y_te)
        logger.info(f"XGBoost trained — test accuracy: {acc:.3f}")

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("Model not trained")
        return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("Model not trained")
        return self.model.predict_proba(X)
