"""ML training/inference consistency (docs/appendix/status.md §3, ML strategy).

Before this, training used advanced_build() features while the strategy
predicted on build() features with no column alignment, so every
prediction raised and was silently swallowed — the ML strategy could never
fire even with a trained model."""
from __future__ import annotations
import pickle
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from ml_models.dataset import (FORWARD_BARS, evaluate, make_dataset, make_labels,
                               passes_gate, time_split)
from scripts.train_ml import enable_ml_in_settings, save_ensemble, train_from_frames
from strategies.ml_based.ml_strategy import MLClassifierStrategy

pytest.importorskip("xgboost")
pytest.importorskip("lightgbm")

ROOT = Path(__file__).resolve().parent.parent


def _ohlcv(n: int, seed: int, with_oi: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 1000 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    df = pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.002, n)),
        "high": close * (1 + abs(rng.normal(0, 0.006, n))),
        "low": close * (1 - abs(rng.normal(0, 0.006, n))),
        "close": close,
        "volume": rng.integers(100_000, 900_000, n).astype(float),
    }, index=pd.date_range("2024-01-01", periods=n, freq="B"))
    if with_oi:
        df["oi"] = 0.0
    return df


def test_labels_unknown_at_the_end_not_hold():
    close = pd.Series(np.linspace(100, 120, 30))
    labels = make_labels(close)
    assert np.isnan(labels[-FORWARD_BARS:]).all()
    assert not np.isnan(labels[:-FORWARD_BARS]).any()
    assert set(labels[:-FORWARD_BARS]) == {2.0}   # steady rise → buy


def test_time_split_leaves_a_gap():
    tr, te = time_split(100, 0.2, gap=5)
    assert tr.stop == 75 and te.start == 80


def test_dataset_tests_on_later_data_for_every_symbol():
    frames = {"A": _ohlcv(400, 1), "B": _ohlcv(400, 2)}
    X_tr, y_tr, X_te, y_te, cols, rows = make_dataset(frames)
    assert set(rows) == {"A", "B"}
    assert "oi" not in cols and "close" not in cols
    # roughly 80/20 within each symbol, minus the gap
    assert abs(len(X_te) - 0.2 * sum(rows.values())) <= 2
    assert len(X_tr) + len(X_te) + 2 * FORWARD_BARS == pytest.approx(sum(rows.values()), abs=2)


def test_train_save_predict_round_trip(tmp_path):
    # Training data has an extra raw column ("oi") the live feed does not.
    frames = {s: _ohlcv(500, i, with_oi=True) for i, s in enumerate(["A", "B", "C"])}
    ensemble, report = train_from_frames(frames, {"ml": {}})
    path = tmp_path / "ensemble.pkl"
    save_ensemble(ensemble, path, trained_on=list(frames), report=report)

    with open(path, "rb") as f:
        loaded = pickle.load(f)["model"]
    strat = MLClassifierStrategy({"ml_min_confidence": 0.0}, model=loaded)
    live_df = _ohlcv(300, 99)                         # no "oi" column
    strat.generate_signal(live_df, "A")

    assert strat._warned == set()                     # no prediction error swallowed
    assert {"accuracy", "baseline_accuracy", "trade_precision"} <= set(report)


def test_missing_trained_column_gives_no_signal():
    class Broken:
        feature_cols = ["not_a_feature"]

        def predict_proba(self, X):
            raise AssertionError("should not be reached")

    strat = MLClassifierStrategy({}, model=Broken())
    assert strat.generate_signal(_ohlcv(300, 3), "A") is None   # missing column → no signal


def test_gate_requires_beating_both_baselines():
    good = {"trade_calls": 50, "accuracy": 0.45, "baseline_accuracy": 0.40,
            "trade_precision": 0.42, "trade_baseline": 0.35}
    assert passes_gate(good)
    assert not passes_gate({**good, "accuracy": 0.39})
    assert not passes_gate({**good, "trade_precision": 0.30})
    assert not passes_gate({**good, "trade_calls": 0})


def test_evaluate_reports_majority_baseline():
    actual = np.array([1, 1, 1, 2, 0])
    report = evaluate(np.array([1, 1, 2, 2, 0]), actual, train_labels=np.array([1, 1, 2]))
    assert report["baseline_class"] == 1
    assert report["baseline_accuracy"] == pytest.approx(0.6)
    assert report["trade_calls"] == 3 and report["trade_precision"] == pytest.approx(2 / 3)


def test_enable_in_settings_is_idempotent_and_keeps_comments(tmp_path):
    path = tmp_path / "settings.yaml"
    shutil.copy(ROOT / "config" / "settings.yaml", path)
    before = path.read_text()

    assert enable_ml_in_settings(path) is True
    assert enable_ml_in_settings(path) is False

    after = path.read_text()
    assert "ml_classifier" in yaml.safe_load(after)["strategies"]["enabled"]
    assert after.count("# Sharpe +3.1 on RELIANCE") == before.count("# Sharpe +3.1 on RELIANCE")
    assert len(after.splitlines()) == len(before.splitlines()) + 1


# ── Gated retrain (CLI + weekly scheduler job) ───────────────────────────────

def _retrain_with(monkeypatch, tmp_path, passes: bool, save_anyway=False):
    import scripts.train_ml as train_ml
    monkeypatch.setattr(train_ml, "_fetch_ohlcv",
                        lambda token, ikey, days: _ohlcv(500, abs(hash(ikey)) % 1000))
    monkeypatch.setattr("ml_models.dataset.passes_gate", lambda report: passes)
    return train_ml.retrain(["RELIANCE", "TCS", "INFY"], token="t",
                            save_anyway=save_anyway, models_dir=tmp_path)


def test_retrain_saves_only_when_it_beats_the_baselines(monkeypatch, tmp_path):
    report = _retrain_with(monkeypatch, tmp_path, passes=False)
    assert report["ok"] and report["saved"] is False
    assert not (tmp_path / "ensemble.pkl").exists()

    report = _retrain_with(monkeypatch, tmp_path, passes=True)
    assert report["saved"] is True
    assert {p.name for p in tmp_path.iterdir()} == {"ensemble.pkl", "xgboost.pkl", "lightgbm.pkl"}


def test_retrain_save_anyway(monkeypatch, tmp_path):
    report = _retrain_with(monkeypatch, tmp_path, passes=False, save_anyway=True)
    assert report["saved"] is True and (tmp_path / "ensemble.pkl").exists()


def test_retrain_without_token_reports_instead_of_exiting(monkeypatch, tmp_path):
    import scripts.train_ml as train_ml
    monkeypatch.setattr(train_ml, "_find_token", lambda: "")
    report = train_ml.retrain(["RELIANCE"], models_dir=tmp_path)
    assert report["ok"] is False and "token" in report["error"].lower()


def test_retrain_job_records_failure(monkeypatch):
    import scripts.train_ml as train_ml
    from scheduler import jobs
    monkeypatch.setattr(train_ml, "retrain", lambda days=730: {"ok": False, "error": "no token"})
    run = jobs.ml_retrain_job()
    assert run.ok is False and "no token" in run.detail
