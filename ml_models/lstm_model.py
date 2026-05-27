import numpy as np
import pickle
from pathlib import Path
from .base_model import BaseMLModel
from utils.logger import get_logger

logger = get_logger("lstm_model")


class LSTMModel(BaseMLModel):
    name = "lstm"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        lstm_cfg = cfg.get("ml", {}).get("lstm", {})
        self.seq_len = lstm_cfg.get("sequence_length", 60)
        self.hidden = lstm_cfg.get("hidden_units", 128)
        self.dropout = lstm_cfg.get("dropout", 0.2)
        self.epochs = lstm_cfg.get("epochs", 50)
        self.batch_size = lstm_cfg.get("batch_size", 32)
        self._scaler = None

    def _build_model(self, n_features: int):
        try:
            from tensorflow import keras
        except ImportError:
            logger.error("tensorflow not installed: pip install tensorflow")
            return None

        model = keras.Sequential([
            keras.layers.Input(shape=(self.seq_len, n_features)),
            keras.layers.LSTM(self.hidden, return_sequences=True),
            keras.layers.Dropout(self.dropout),
            keras.layers.LSTM(self.hidden // 2),
            keras.layers.Dropout(self.dropout),
            keras.layers.Dense(64, activation="relu"),
            keras.layers.Dense(3, activation="softmax"),
        ])
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=1e-3),
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )
        return model

    def _make_sequences(self, X: np.ndarray, y: np.ndarray):
        Xs, ys = [], []
        for i in range(self.seq_len, len(X)):
            Xs.append(X[i - self.seq_len:i])
            ys.append(y[i])
        return np.array(Xs), np.array(ys)

    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        try:
            from sklearn.preprocessing import StandardScaler
            from tensorflow import keras
        except ImportError:
            logger.error("tensorflow/sklearn not installed")
            return

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        self._scaler = scaler

        X_seq, y_seq = self._make_sequences(X_scaled, y)
        split = int(len(X_seq) * 0.8)
        X_tr, X_te = X_seq[:split], X_seq[split:]
        y_tr, y_te = y_seq[:split], y_seq[split:]

        self.model = self._build_model(X.shape[1])
        if self.model is None:
            return

        callbacks = [
            keras.callbacks.EarlyStopping(patience=10, restore_best_weights=True),
            keras.callbacks.ReduceLROnPlateau(patience=5, factor=0.5),
        ]
        self.model.fit(
            X_tr, y_tr,
            validation_data=(X_te, y_te),
            epochs=self.epochs,
            batch_size=self.batch_size,
            callbacks=callbacks,
            verbose=0,
        )
        self.is_trained = True
        loss, acc = self.model.evaluate(X_te, y_te, verbose=0)
        logger.info(f"LSTM trained — val accuracy: {acc:.3f}")

    def predict(self, X: np.ndarray) -> np.ndarray:
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.is_trained or self.model is None:
            raise RuntimeError("Model not trained")
        if self._scaler is not None:
            X = self._scaler.transform(X)
        if len(X) < self.seq_len:
            return np.array([[0.0, 1.0, 0.0]])
        X_seq = X[-self.seq_len:].reshape(1, self.seq_len, -1)
        return self.model.predict(X_seq, verbose=0)

    def save(self) -> None:
        if self.model is not None:
            self.model.save(str(self.model_dir / "lstm_weights"))
        scaler_path = self.model_dir / "lstm_scaler.pkl"
        with open(scaler_path, "wb") as f:
            pickle.dump(self._scaler, f)

    def load(self) -> bool:
        try:
            from tensorflow import keras
            model_path = self.model_dir / "lstm_weights"
            if not model_path.exists():
                return False
            self.model = keras.models.load_model(str(model_path))
            scaler_path = self.model_dir / "lstm_scaler.pkl"
            if scaler_path.exists():
                with open(scaler_path, "rb") as f:
                    self._scaler = pickle.load(f)
            self.is_trained = True
            return True
        except Exception:
            return False
