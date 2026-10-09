"""One definition of the ML inputs, shared by training and live prediction.

Training (scripts/train_ml.py, ModelTrainer) and MLClassifierStrategy must
build exactly the same feature columns in the same order, or predict_proba
fails on a shape mismatch. Everything here uses FeatureBuilder.build() —
offline, deterministic and cheap enough to run on every bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from feature_engine.feature_builder import FeatureBuilder

# Raw price/volume columns, plus raw columns some data sources add (open
# interest), are never model inputs.
NON_FEATURE_COLS = {"open", "high", "low", "close", "volume", "oi"}

FORWARD_BARS = 5         # label horizon
LABEL_THRESHOLD = 0.005  # ±0.5% over FORWARD_BARS → buy/sell, otherwise hold


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    return FeatureBuilder().build(df)


def feature_columns(features: pd.DataFrame) -> list[str]:
    return [c for c in features.columns
            if c not in NON_FEATURE_COLS and pd.api.types.is_numeric_dtype(features[c])]


def make_labels(close: pd.Series, forward_bars: int = FORWARD_BARS,
                threshold: float = LABEL_THRESHOLD) -> np.ndarray:
    """3-class labels: 0=sell, 1=hold, 2=buy. The last `forward_bars` rows
    have no known future and are NaN (not "hold")."""
    future_return = (close.shift(-forward_bars) / close - 1).to_numpy(dtype=float)
    labels = np.where(future_return > threshold, 2.0,
                      np.where(future_return < -threshold, 0.0, 1.0))
    labels[np.isnan(future_return)] = np.nan
    return labels


def time_split(n: int, test_ratio: float = 0.2, gap: int = FORWARD_BARS) -> tuple[slice, slice]:
    """Chronological train/test slices with a gap, so no training label
    looks forward into the test period."""
    split = int(n * (1 - test_ratio))
    return slice(0, max(split - gap, 0)), slice(split, n)


def make_dataset(frames: dict[str, pd.DataFrame], test_ratio: float = 0.2,
                 forward_bars: int = FORWARD_BARS, threshold: float = LABEL_THRESHOLD):
    """Build a train/test set from several symbols' OHLCV frames.

    Each symbol is split by time on its own (first 80% train, last 20% test,
    with a `forward_bars` gap), so the test set is genuinely later data for
    every symbol — not the last few symbols over the same dates.

    Returns (X_train, y_train, X_test, y_test, feature_cols, per_symbol_rows).
    """
    feature_cols: list[str] | None = None
    parts_tr, parts_te = [], []
    rows: dict[str, int] = {}
    for sym, raw in frames.items():
        feats = build_features(raw)
        if feature_cols is None:
            feature_cols = feature_columns(feats)
        labels = make_labels(feats["close"], forward_bars, threshold)
        X = feats.reindex(columns=feature_cols).to_numpy(dtype=float)
        valid = ~np.isnan(X).any(axis=1) & ~np.isnan(labels)
        X, y = X[valid], labels[valid].astype(int)
        if len(X) < 50:
            continue
        tr, te = time_split(len(X), test_ratio, forward_bars)
        parts_tr.append((X[tr], y[tr]))
        parts_te.append((X[te], y[te]))
        rows[sym] = len(X)
    if not parts_tr:
        empty = np.empty((0, len(feature_cols or [])))
        return empty, np.empty(0, int), empty, np.empty(0, int), feature_cols or [], rows
    X_tr = np.vstack([p[0] for p in parts_tr]); y_tr = np.concatenate([p[1] for p in parts_tr])
    X_te = np.vstack([p[0] for p in parts_te]); y_te = np.concatenate([p[1] for p in parts_te])
    return X_tr, y_tr, X_te, y_te, feature_cols, rows


def evaluate(predicted: np.ndarray, actual: np.ndarray, train_labels: np.ndarray) -> dict:
    """Out-of-sample accuracy next to the naive baseline (always predict the
    most common training class), plus how often buy/sell calls were right —
    the only predictions the strategy actually trades."""
    majority = int(np.bincount(train_labels, minlength=3).argmax())
    trade = predicted != 1
    counts = np.bincount(actual, minlength=3)
    return {
        "accuracy": float(np.mean(predicted == actual)),
        "baseline_accuracy": float(np.mean(actual == majority)),
        "baseline_class": majority,
        "trade_calls": int(trade.sum()),
        "trade_precision": float(np.mean(predicted[trade] == actual[trade])) if trade.any() else 0.0,
        # Hit rate of blindly calling the more common move (buy or sell) every time.
        "trade_baseline": float(max(counts[0], counts[2]) / max(len(actual), 1)),
        "test_samples": int(len(actual)),
    }


def feature_row(df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray | None:
    """The latest bar's model input, in the trained column order. None if the
    data is too short or a trained column is missing."""
    feats = build_features(df)
    if feats.empty or any(c not in feats.columns for c in feature_cols):
        return None
    row = feats[feature_cols].iloc[-1:].to_numpy(dtype=float)
    return None if np.isnan(row).any() else row


def passes_gate(report: dict) -> bool:
    """Worth trading only if it beats both naive baselines out of sample."""
    return (report["trade_calls"] > 0
            and report["accuracy"] > report["baseline_accuracy"]
            and report["trade_precision"] > report["trade_baseline"])
