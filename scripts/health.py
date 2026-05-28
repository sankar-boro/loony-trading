#!/usr/bin/env python
"""
System Health Check
===================

Checks every major component in one go:
  • Upstox token (age, validity, live LTP fetch)
  • Dashboard API (all endpoints)
  • Strategy engine (import + load)
  • ML model (ensemble exists and loads)
  • Data files (equity curve, positions, daily P&L)
  • Python packages (required imports)
  • Disk / log sizes

Usage:
    python scripts/health.py
    python scripts/health.py --quiet     # only show failures
    python scripts/health.py --fix       # attempt auto-fixes where possible
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

G  = "\033[92m"; R  = "\033[91m"; Y  = "\033[93m"
B  = "\033[1m";  DIM = "\033[2m"; E  = "\033[0m"
C  = "\033[96m"

PASS  = f"{G}  PASS{E}"
FAIL  = f"{R}  FAIL{E}"
WARN  = f"{Y}  WARN{E}"
SKIP  = f"{DIM}  SKIP{E}"

_quiet = "--quiet" in sys.argv or "-q" in sys.argv
_fix   = "--fix"   in sys.argv

_results: list[tuple[str, str, str]] = []   # (label, status, detail)


def check(label: str, fn: Callable) -> bool:
    """Run fn(); record pass/fail/warn; return True on pass."""
    try:
        result = fn()
        if result is True or result is None:
            status, detail = PASS, ""
        elif result is False:
            status, detail = FAIL, ""
        elif isinstance(result, tuple):
            ok, detail = result
            status = PASS if ok is True else (WARN if ok == "warn" else FAIL)
        else:
            status, detail = PASS, str(result)
        ok_bool = status == PASS
    except Exception as exc:
        status, detail = FAIL, str(exc)[:80]
        ok_bool = False

    _results.append((label, status, detail))
    if not _quiet or status != PASS:
        pad = max(0, 40 - len(label))
        print(f"  {label}{' ' * pad}{status}  {DIM}{detail}{E}")
    return ok_bool


def section(title: str):
    print(f"\n{B}  {title}{E}")
    print("  " + "─" * 60)


# ─────────────────────────────────────────────────────────────────────────────

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


def main():
    _load_env()
    print(f"\n{B}{C}  Loony Trading — Health Check{E}  {DIM}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{E}\n")

    # ── Token ─────────────────────────────────────────────────────────────────
    section("Upstox Token")
    _tok = [""]  # mutable container so closures can share it

    def _check_token():
        tf = ROOT / "data" / "upstox_token.json"
        env_tok = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
        if tf.exists():
            try:
                d = json.loads(tf.read_text())
                tok = d.get("access_token", "")
                age_h = (time.time() - d.get("obtained_at", 0)) / 3600
                _tok[0] = tok or env_tok
                if age_h > 23:
                    return False, f"expired ({age_h:.1f}h old)"
                if age_h > 20:
                    return "warn", f"{age_h:.1f}h old — expires soon"
                return True, f"{age_h:.1f}h old"
            except Exception as exc:
                return False, str(exc)
        if env_tok:
            _tok[0] = env_tok
            return "warn", "from env var only (no age info)"
        return False, "no token file and no env var"

    token_ok = check("Token file / env var", _check_token)

    def _check_ltp():
        if not _tok[0]:
            return False, "no token"
        import requests
        key = "NSE_INDEX%7CNifty%2050"
        r = requests.get(
            f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={key}",
            headers={"Authorization": f"Bearer {_tok[0]}", "Accept": "application/json"},
            timeout=6,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            for v in data.values():
                ltp = v.get("last_price", 0)
                if ltp:
                    return True, f"NIFTY50 LTP = {ltp:,.2f}"
            return "warn", "LTP = 0 (market closed?)"
        if r.status_code == 401:
            return False, "401 Unauthorized — token expired"
        return "warn", f"HTTP {r.status_code}"

    check("Live LTP fetch (NIFTY50)", _check_ltp)

    # ── Dashboard ─────────────────────────────────────────────────────────────
    section("Dashboard API")
    api_base = "http://localhost:8000"

    def _check_endpoint(path: str):
        def _fn():
            import requests
            try:
                r = requests.get(f"{api_base}{path}", timeout=3)
                if r.status_code == 200:
                    return True, f"{r.status_code} ({len(r.content)}B)"
                return False, f"HTTP {r.status_code}"
            except requests.exceptions.ConnectionError:
                return "warn", "not running (start with: ./loony.sh start)"
        return _fn

    for path in ["/api/status", "/api/equity", "/api/positions",
                 "/api/trades", "/api/config", "/api/market"]:
        check(f"GET {path}", _check_endpoint(path))

    # ── Strategy engine ───────────────────────────────────────────────────────
    section("Strategy Engine")

    def _check_engine_import():
        from strategies.meta_engine import MetaStrategyEngine
        return True, "MetaStrategyEngine importable"

    check("MetaStrategyEngine import", _check_engine_import)

    def _check_engine_load():
        from strategies.meta_engine import MetaStrategyEngine
        cfg = {"strategies": {"enabled": [], "weights": {}},
               "risk": {}, "execution": {}, "data": {}, "system": {"mode": "paper"}}
        e = MetaStrategyEngine(cfg)
        n = len(e.strategies)
        return (True if n >= 15 else "warn"), f"{n} strategies loaded"

    check("MetaStrategyEngine loads", _check_engine_load)

    def _check_feature_builder():
        from feature_engine.feature_builder import FeatureBuilder
        import numpy as np, pandas as pd
        fb = FeatureBuilder()
        idx = pd.date_range("2024-01-01", periods=250, freq="B")
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "open":   rng.uniform(100, 200, 250),
            "high":   rng.uniform(150, 250, 250),
            "low":    rng.uniform(80,  150, 250),
            "close":  rng.uniform(100, 200, 250),
            "volume": rng.integers(1_000_000, 10_000_000, 250).astype(float),
        }, index=idx)
        result = fb.build(df)
        return (len(result) > 0), f"{len(result.columns)} features on {len(result)} rows"

    check("FeatureBuilder builds", _check_feature_builder)

    # ── ML models ─────────────────────────────────────────────────────────────
    section("ML Models")

    def _check_ensemble():
        ens_path = ROOT / "models" / "ensemble.pkl"
        if not ens_path.exists():
            return False, "models/ensemble.pkl missing — run: python scripts/train_ml.py"
        import pickle
        with open(ens_path, "rb") as f:
            data = pickle.load(f)
        model   = data.get("model")
        n_samp  = data.get("n_samples", 0)
        saved   = data.get("saved_at", 0)
        age_d   = (time.time() - saved) / 86400 if saved else 0
        if model is None or not hasattr(model, "predict_proba"):
            return False, "ensemble model object invalid"
        return True, f"{n_samp} training samples  •  {age_d:.0f}d old"

    check("ML ensemble (models/ensemble.pkl)", _check_ensemble)

    def _check_sub_models():
        missing = [n for n in ["xgboost.pkl", "lightgbm.pkl"]
                   if not (ROOT / "models" / n).exists()]
        if missing:
            return "warn", f"missing: {', '.join(missing)}"
        return True, "xgboost.pkl + lightgbm.pkl present"

    check("Individual model files", _check_sub_models)

    # ── Data files ────────────────────────────────────────────────────────────
    section("Data Files")

    def _check_data_file(path: Path, label: str, min_lines: int = 1):
        def _fn():
            if not path.exists():
                return "warn", f"not found ({path.name})"
            size = path.stat().st_size
            if path.suffix == ".jsonl":
                lines = sum(1 for _ in path.open() if _.strip())
                if lines < min_lines:
                    return "warn", f"{lines} records (expected ≥{min_lines})"
                return True, f"{lines} records ({size // 1024}KB)"
            return True, f"{size // 1024}KB"
        _fn.__name__ = label
        return _fn

    check("data/live_positions.json",  _check_data_file(ROOT / "data" / "live_positions.json", "live_positions"))
    check("data/equity_curve.jsonl",   _check_data_file(ROOT / "data" / "equity_curve.jsonl",  "equity_curve",  min_lines=5))
    check("data/daily_pnl.jsonl",      _check_data_file(ROOT / "data" / "daily_pnl.jsonl",     "daily_pnl",     min_lines=1))
    check("logs/paper_trades.jsonl",   _check_data_file(ROOT / "logs" / "paper_trades.jsonl",   "paper_trades",  min_lines=1))
    check("config/settings.yaml",      _check_data_file(ROOT / "config" / "settings.yaml",     "settings"))

    # ── Python packages ───────────────────────────────────────────────────────
    section("Python Packages")

    REQUIRED_PACKAGES = [
        ("fastapi",     "fastapi"),
        ("uvicorn",     "uvicorn"),
        ("httpx",       "httpx"),
        ("pandas",      "pandas"),
        ("numpy",       "numpy"),
        ("xgboost",     "xgboost"),
        ("lightgbm",    "lightgbm"),
        ("sklearn",     "sklearn"),
        ("requests",    "requests"),
        ("yaml",        "yaml"),
    ]

    for label, pkg in REQUIRED_PACKAGES:
        def _check_pkg(p=pkg):
            import importlib
            mod = importlib.import_module(p)
            ver = getattr(mod, "__version__", "?")
            return True, f"v{ver}"
        check(label, _check_pkg)

    # ── Disk / logs ───────────────────────────────────────────────────────────
    section("Disk & Logs")

    def _check_log_sizes():
        log_dir = ROOT / "logs"
        if not log_dir.exists():
            return "warn", "logs/ directory missing"
        total = sum(f.stat().st_size for f in log_dir.rglob("*") if f.is_file())
        total_mb = total / 1_048_576
        if total_mb > 500:
            return "warn", f"{total_mb:.0f}MB — consider archiving"
        return True, f"{total_mb:.1f}MB"

    check("Log directory size", _check_log_sizes)

    def _check_disk():
        import shutil
        stat = shutil.disk_usage(ROOT)
        free_gb = stat.free / 1_073_741_824
        if free_gb < 1:
            return False, f"only {free_gb:.2f}GB free"
        if free_gb < 5:
            return "warn", f"{free_gb:.1f}GB free"
        return True, f"{free_gb:.1f}GB free"

    check("Disk space", _check_disk)

    # ── Summary ───────────────────────────────────────────────────────────────
    passes  = sum(1 for _, s, _ in _results if s == PASS)
    warns   = sum(1 for _, s, _ in _results if s == WARN)
    fails   = sum(1 for _, s, _ in _results if s == FAIL)
    total   = len(_results)

    print(f"\n{'  ' + '─' * 60}")
    color = G if fails == 0 else R
    print(f"  {color}{B}Results:{E}  "
          f"{G}{passes} passed{E}  "
          f"{Y}{warns} warnings{E}  "
          f"{R}{fails} failed{E}  "
          f"{DIM}({total} checks){E}")

    if fails > 0:
        print(f"\n  {R}Failed checks:{E}")
        for label, status, detail in _results:
            if status == FAIL:
                print(f"    • {label}: {detail}")

    if warns > 0 and not _quiet:
        print(f"\n  {Y}Warnings:{E}")
        for label, status, detail in _results:
            if status == WARN:
                print(f"    • {label}: {detail}")

    print()
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
