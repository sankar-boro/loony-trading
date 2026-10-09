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
    python scripts/train_ml.py --enable               # also enable ml_classifier if it beats the baselines
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


def _find_token() -> str:
    """Valid token from the environment or data/upstox_token.json, or ""."""
    _load_env()
    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if token:
        return token
    tf = ROOT / "data" / "upstox_token.json"
    try:
        from data_engine.upstox.auth import token_hours_left
        d = json.loads(tf.read_text())
        if token_hours_left(d.get("obtained_at", 0)) > 0:
            return d.get("access_token", "")
    except Exception:
        pass
    return ""


def _get_token() -> str:
    tf = ROOT / "data" / "upstox_token.json"
    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token and tf.exists():
        try:
            d = json.loads(tf.read_text())
            token = d.get("access_token", "")
            from data_engine.upstox.auth import token_hours_left
            age_h = (time.time() - d.get("obtained_at", 0)) / 3600
            if token_hours_left(d.get("obtained_at", 0)) <= 0:
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
    parser.add_argument("--token",       help="Upstox access token (optional)")
    parser.add_argument("--enable",      action="store_true",
                        help="Add ml_classifier to strategies.enabled if it beats the baselines")
    parser.add_argument("--save-anyway", action="store_true",
                        help="Save the model even if it does not beat the baselines")
    args = parser.parse_args()

    _load_env()
    token = args.token or _get_token()
    syms  = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or DEFAULT_SYMBOLS

    print(bold(f"\n  ML Model Trainer — {len(syms)} symbols, {args.days}-day window"))
    print(f"  Symbols: {', '.join(syms)}\n")

    report = retrain(syms, args.days, token, save_anyway=args.save_anyway, verbose=True)
    if not report.get("ok"):
        print(f"\n{R}{report['error']}{E}")
        sys.exit(1)

    from ml_models.dataset import passes_gate
    if report["saved"] and passes_gate(report):
        if args.enable:
            changed = enable_ml_in_settings(ROOT / "config" / "settings.yaml")
            print(f"  {green('ml_classifier enabled')} in config/settings.yaml" if changed
                  else f"  {dim('ml_classifier already enabled')}")
        else:
            print(f"  {green('Beats both baselines.')} Backtest it, then re-run with --enable "
                  "(or add ml_classifier to strategies.enabled).")
    elif args.enable:
        print(f"  {dim('--enable ignored: the model did not beat the baselines.')}")
    print()


_TRAIN_CFG = {
    "ml": {
        "xgboost":  {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.05},
        "lightgbm": {"num_leaves": 63,   "n_estimators": 300, "learning_rate": 0.05},
    }
}


def retrain(symbols: list[str] | None = None, days: int = 730, token: str | None = None,
            save_anyway: bool = False, verbose: bool = False,
            models_dir: Path | None = None) -> dict:
    """Fetch history, train, evaluate out of sample, and save the ensemble to
    models/ensemble.pkl — but only if it beats the naive baselines (or
    save_anyway), so a weak retrain never replaces a working model.
    Never enables the strategy. Used by the CLI and the weekly scheduler job;
    returns a report dict instead of exiting."""
    from ml_models.dataset import passes_gate
    models_dir = Path(models_dir or ROOT / "models")
    token = token or _find_token()
    if not token:
        return {"ok": False, "error": "No valid Upstox token. Run: python scripts/upstox_login.py"}
    syms = symbols or DEFAULT_SYMBOLS

    frames = {}
    for sym in syms:
        ikey = INSTRUMENTS.get(sym)
        df_raw = _fetch_ohlcv(token, ikey, days) if ikey else None
        if df_raw is None or df_raw.empty:
            if verbose:
                print(f"  {yellow(f'{sym}: no data — skipped')}")
            continue
        frames[sym] = df_raw
        if verbose:
            print(f"  {dim(sym)} {green('ok')} ({len(df_raw)} bars)")

    try:
        ensemble, report = train_from_frames(frames, _TRAIN_CFG)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    passed = passes_gate(report)
    report.update({"ok": True, "passed_gate": passed, "saved": False})
    if verbose:
        _print_report(report)
    if passed or save_anyway:
        for m in ensemble.models:   # members too, for main.py's fallback path
            m.model_dir = models_dir
            m.save()
        ens_path = models_dir / "ensemble.pkl"
        save_ensemble(ensemble, ens_path, trained_on=list(frames), report=report)
        report["saved"] = True
        if verbose:
            print(f"\n  {green('Ensemble saved')} → {ens_path}")
    elif verbose:
        print(f"\n  {yellow('Does not beat the naive baselines out of sample — existing model kept.')}"
              f"\n  {dim('Use --save-anyway to save it regardless.')}")
    return report


def train_from_frames(frames: dict, cfg: dict, model_dir: Path | None = None):
    """Train XGBoost + LightGBM on a per-symbol time split and evaluate the
    ensemble on the held-out later 20% of every symbol. Returns
    (ensemble, report). Raises ValueError when there is too little data.

    With model_dir, the members are also saved there as xgboost.pkl /
    lightgbm.pkl (main.py's fallback when models/ensemble.pkl is missing)."""
    import numpy as np
    from ml_models.dataset import make_dataset, evaluate
    from ml_models.xgb_model import XGBoostModel
    from ml_models.lgbm_model import LightGBMModel
    from ml_models.ensemble import EnsembleModel

    X_tr, y_tr, X_te, y_te, feature_cols, rows = make_dataset(frames)
    if len(X_tr) < 100 or len(X_te) < 20:
        raise ValueError(f"Need ≥100 training samples; got {len(X_tr)} "
                         f"(test {len(X_te)}). Use more symbols or --days.")

    trained = []
    for m in (XGBoostModel(cfg), LightGBMModel(cfg)):
        m.feature_cols = feature_cols
        m.train(X_tr, y_tr)
        if m.is_trained:
            if model_dir is not None:
                m.model_dir = Path(model_dir)
                m.save()
            trained.append(m)
    if not trained:
        raise ValueError("All models failed to train (is xgboost / lightgbm installed?)")

    ensemble = EnsembleModel(trained)
    ensemble.feature_cols = feature_cols
    # Weights from the test split would leak it into the evaluation below,
    # so members keep equal weight.
    report = evaluate(ensemble.predict(X_te), y_te, y_tr)
    report.update({
        "train_samples": int(len(X_tr)),
        "features": len(feature_cols),
        "symbols": rows,
        "class_counts_train": {k: int(v) for k, v in zip(("sell", "hold", "buy"),
                                                           np.bincount(y_tr, minlength=3))},
    })
    return ensemble, report


def save_ensemble(ensemble, path: Path, trained_on: list, report: dict) -> None:
    import pickle
    path.parent.mkdir(exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump({
            "model":        ensemble,
            "feature_cols": ensemble.feature_cols,
            "trained_on":   trained_on,
            "n_samples":    report["train_samples"],
            "report":       report,
            "saved_at":     time.time(),
        }, f)


def enable_ml_in_settings(path: Path) -> bool:
    """Append ml_classifier to strategies.enabled in settings.yaml, keeping the
    file's comments. Returns False if it was already enabled."""
    lines = path.read_text().splitlines(keepends=True)
    in_strategies = in_enabled = False
    last_item = None
    for i, line in enumerate(lines):
        if not line.startswith(" ") and line.strip():
            in_strategies = line.startswith("strategies:")
            in_enabled = False
            continue
        if in_strategies and line.strip() == "enabled:":
            in_enabled = True
            continue
        if in_enabled:
            stripped = line.strip()
            if stripped.startswith("- "):
                if stripped[2:].split("#")[0].strip() == "ml_classifier":
                    return False
                last_item = i
            elif stripped and not stripped.startswith("#"):
                break
    if last_item is None:
        raise ValueError(f"Could not find strategies.enabled in {path}")
    indent = lines[last_item][: len(lines[last_item]) - len(lines[last_item].lstrip())]
    lines.insert(last_item + 1,
                 f"{indent}- ml_classifier         # enabled by train_ml.py --enable on "
                 f"{date.today().isoformat()}\n")
    path.write_text("".join(lines))
    return True


def _print_report(r: dict) -> None:
    pct = lambda x: f"{x * 100:.1f}%"
    names = {0: "sell", 1: "hold", 2: "buy"}
    print(f"\n  {bold('Out-of-sample results')} (last 20% of each symbol's history, never trained on)")
    print(f"  Train samples      {r['train_samples']}  ×  {r['features']} features   "
          f"{dim(str(r['class_counts_train']))}")
    print(f"  Test samples       {r['test_samples']}")
    print(f"  Accuracy           {pct(r['accuracy'])}   vs always-'{names[r['baseline_class']]}' "
          f"baseline {pct(r['baseline_accuracy'])}")
    print(f"  Buy/sell calls     {r['trade_calls']}, right {pct(r['trade_precision'])}   "
          f"vs always calling the commoner move {pct(r['trade_baseline'])}")


if __name__ == "__main__":
    main()
