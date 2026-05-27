import numpy as np
from .base_model import BaseMLModel
from utils.logger import get_logger

logger = get_logger("lgbm_model")


class LightGBMModel(BaseMLModel):
    name = "lightgbm"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        lgbm_cfg = cfg.get("ml", {}).get("lightgbm", {})
        self.num_leaves = lgbm_cfg.get("num_leaves", 63)
        self.n_estimators = lgbm_cfg.get("n_estimators", 300)
        self.learning_rate = lgbm_cfg.get("learning_rate", 0.05)

    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        try:
            from lightgbm import LGBMClassifier
        except ImportError:
            logger.error("lightgbm not installed: pip install lightgbm")
            return

        X_tr, X_te, y_tr, y_te = self.train_test_split_time(X, y)
        self.model = LGBMClassifier(
            num_leaves=self.num_leaves,
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            random_state=42,
            verbose=-1,
        )
        self.model.fit(
            X_tr, y_tr,
            eval_set=[(X_te, y_te)],
            callbacks=[],
        )
        self.is_trained = True
        acc = np.mean(self.model.predict(X_te) == y_te)
        logger.info(f"LightGBM trained — test accuracy: {acc:.3f}")

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("Model not trained")
        return self.model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("Model not trained")
        return self.model.predict_proba(X)
