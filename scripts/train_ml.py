#!/usr/bin/env python
"""
ML Model Trainer
================

Fetches 2-year historical data for a set of NSE symbols, builds features,
trains XGBoost + LightGBM classifiers, and saves them to models/.

The trained ensemble is automatically loaded by MetaStrategyEngine when
the paper trader or signal scanner starts.

Usage:
    python scripts/train_ml.py
    python scripts/train_ml.py --symbols RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK,SBIN
    python scripts/train_ml.py --days 730             # 2-year window (default)
    python scripts/train_ml.py --no-validate          # skip OOS validation print
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
DIM = "\033[2m"; C = "\033[96m"; E = "\033[0m"

def green(s):  return f"{G}{s}{E}"
def red(s):    return f"{R}{s}{E}"
def bold(s):   return f"{B}{s}{E}"
def dim(s):    return f"{DIM}{s}{E}"
def yellow(s): return f"{Y}{s}{E}"

from config.instruments import INSTRUMENTS, get_nifty50_symbols

DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN",
                   "AXISBANK", "KOTAKBANK", "WIPRO", "HCLTECH"]


def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v


def _get_token() -> str:
    tf = ROOT / "data" / "upstox_token.json"
    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token and tf.exists():
        try:
            d = json.loads(tf.read_text())
            token = d.get("access_token", "")
            age_h = (time.time() - d.get("obtained_at", 0)) / 3600
            if age_h > 23:
                print(f"{R}Token expired ({age_h:.1f}h old). Run: python scripts/upstox_login.py{E}")
                sys.exit(1)
        except Exception:
            pass
    if not token:
        print(f"{R}No token found. Run: python scripts/upstox_login.py{E}")
        sys.exit(1)
    return token


def _fetch_ohlcv(token: str, instrument_key: str, days: int):
    import requests
    import pandas as pd
    key = instrument_key.replace("|", "%7C").replace(" ", "%20")
    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=days)).isoformat()
    url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
    try:
        r = requests.get(url,
                         headers={"Authorization": f"Bearer {token}",
                                  "Accept": "application/json"},
                         timeout=12)
        if r.status_code != 200:
            return pd.DataFrame()
        candles = r.json().get("data", {}).get("candles", [])
    except Exception as exc:
        print(f"  {yellow(f'HTTP error: {exc}')}")
        return pd.DataFrame()
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].apply(float)
    return df


def main():
    parser = argparse.ArgumentParser(description="Train XGBoost + LightGBM ML classifiers")
    parser.add_argument("--symbols",     default="",
                        help="Comma-separated symbols (default: 6-symbol set)")
    parser.add_argument("--days",        type=int, default=730,
                        help="History window in calendar days (default: 730 = 2 years)")
    parser.add_argument("--no-validate", action="store_true",
                        help="Skip out-of-sample accuracy table")
    parser.add_argument("--token",       help="Upstox access token (optional)")
    args = parser.parse_args()

    _load_env()
    token = args.token or _get_token()
    syms  = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or DEFAULT_SYMBOLS

    print(bold(f"\n  ML Model Trainer — {len(syms)} symbols, {args.days}-day window"))
    print(f"  Symbols: {', '.join(syms)}\n")

    from feature_engine.feature_builder import FeatureBuilder
    from ml_models.base_model import BaseMLModel
    from ml_models.xgb_model import XGBoostModel
    from ml_models.lgbm_model import LightGBMModel
    from ml_models.ensemble import EnsembleModel

    fb  = FeatureBuilder()
    cfg = {
        "ml": {
            "xgboost":       {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.05},
            "lightgbm":      {"num_leaves": 63,   "n_estimators": 300, "learning_rate": 0.05},
            "forward_bars":  5,
            "label_threshold": 0.005,
        }
    }

    # ── Step 1: load data ─────────────────────────────────────────────────────
    import numpy as np
    import pandas as pd

    all_X: list[np.ndarray] = []
    all_y: list[np.ndarray] = []
    feature_cols: list[str] = []
    exclude = {"open", "high", "low", "close", "volume"}

    print(f"  {dim('Fetching and building features (including advanced: VIX, FII/DII, cross-asset)...')}")
    for sym in syms:
        ikey = INSTRUMENTS.get(sym)
        if not ikey:
            print(f"  {yellow(f'Unknown symbol {sym} — skipped')}")
            continue
        df_raw = _fetch_ohlcv(token, ikey, args.days)
        if df_raw.empty:
            print(f"  {yellow(f'{sym}: no data')}")
            continue
        try:
            df = fb.advanced_build(df_raw, symbol=sym, include_cross_asset=True)
        except Exception as exc:
            print(f"  {yellow(f'{sym}: advanced build failed ({exc}), falling back')}")
            try:
                df = fb.build(df_raw)
            except Exception as exc2:
                print(f"  {yellow(f'{sym}: feature build failed — {exc2}')}")
                continue
        if len(df) < 100:
            print(f"  {yellow(f'{sym}: only {len(df)} bars after feature build — skipped')}")
            continue

        cols = [c for c in df.columns if c not in exclude]
        if not feature_cols:
            feature_cols = cols

        labels = BaseMLModel.make_labels(df, forward_bars=5, threshold=0.005)
        X = df[cols].values
        y = labels
        valid = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
        X, y = X[valid], y[valid].astype(int)

        all_X.append(X)
        all_y.append(y)
        print(f"  {dim(sym)} {green('ok')} ({len(df)} bars → {len(X)} samples)")

    if not all_X:
        print(f"\n{R}No usable data. Cannot train.{E}")
        sys.exit(1)

    X_all = np.vstack(all_X)
    y_all = np.concatenate(all_y)
    print(f"\n  Combined dataset: {len(X_all)} samples × {len(feature_cols)} features")
    classes, counts = np.unique(y_all, return_counts=True)
    dist = {int(c): int(n) for c, n in zip(classes, counts)}
    print(f"  Class distribution: sell={dist.get(0,0)}  hold={dist.get(1,0)}  buy={dist.get(2,0)}")

    if len(X_all) < 100:
        print(f"\n{R}Need ≥100 samples to train. Got {len(X_all)}.{E}")
        sys.exit(1)

    # ── Step 2: train ─────────────────────────────────────────────────────────
    print(f"\n  {bold('Training models...')}")

    models: list[BaseMLModel] = [
        XGBoostModel(cfg),
        LightGBMModel(cfg),
    ]

    split = int(len(X_all) * 0.8)
    X_tr, X_te = X_all[:split], X_all[split:]
    y_tr, y_te = y_all[:split], y_all[split:]

    trained = []
    for m in models:
        m.feature_cols = feature_cols
        t0 = time.perf_counter()
        try:
            m.train(X_tr, y_tr)
            m.save()
            elapsed = time.perf_counter() - t0
            if not args.no_validate:
                acc = np.mean(m.predict(X_te) == y_te) * 100
                print(f"  {m.name:<14}  {green('trained')}  OOS accuracy: {acc:.1f}%  ({elapsed:.1f}s)")
            else:
                print(f"  {m.name:<14}  {green('trained')}  ({elapsed:.1f}s)")
            trained.append(m)
        except Exception as exc:
            print(f"  {m.name:<14}  {red(f'FAILED: {exc}')}")

    if not trained:
        print(f"\n{R}All models failed to train.{E}")
        sys.exit(1)

    # ── Step 3: build and save ensemble ──────────────────────────────────────
    ensemble = EnsembleModel(trained)
    ensemble.update_weights_by_accuracy(X_te, y_te)
    ensemble.feature_cols = feature_cols

    import pickle
    models_dir = ROOT / "models"
    models_dir.mkdir(exist_ok=True)
    ens_path = models_dir / "ensemble.pkl"
    with open(ens_path, "wb") as f:
        pickle.dump({
            "model":        ensemble,
            "feature_cols": feature_cols,
            "trained_on":   syms,
            "n_samples":    len(X_all),
            "saved_at":     time.time(),
        }, f)

    print(f"\n  {green('Ensemble saved')} → {ens_path}")
    print(f"  Ensemble weights: " +
          "  ".join(f"{m.name}={w:.3f}" for m, w in zip(trained, ensemble.weights)))

    # ── Step 4: quick sanity predict ─────────────────────────────────────────
    sample_proba = ensemble.predict_proba(X_te[:5])
    preds = np.argmax(sample_proba, axis=1)
    label_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
    print(f"\n  Sample predictions (first 5 OOS rows):")
    for i, (pred, true) in enumerate(zip(preds, y_te[:5])):
        match = "✓" if pred == true else "✗"
        print(f"    [{i}] pred={label_map[pred]}  true={label_map[int(true)]} {match}")

    print(f"\n  {bold('Done.')} Run the paper trader or signal scanner to use the model.\n")


if __name__ == "__main__":
    main()
