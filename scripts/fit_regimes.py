#!/usr/bin/env python3
"""
Fit the per-symbol HMM regime models (strategies/hmm_regime.py).

Each model is checked out of sample before it is used: on the last quarter
of the bars it must explain returns better than a single regime, and its
regimes must last at least three bars on average. Models that fail are saved
as unusable, and RegimeDetector keeps using its ADX rules for that symbol.
The scheduler refits weekly when scheduler.regime_refit_enabled is true.

    python scripts/fit_regimes.py                    # Nifty 50 stocks + main indices
    python scripts/fit_regimes.py --all --days 1095  # whole universe, 3 years
    python scripts/fit_regimes.py --symbols RELIANCE,TCS
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

INDICES = ["NIFTY50", "BANKNIFTY"]


def fit_regimes(symbols: list[str], days: int = 1095, frames: dict | None = None) -> list[dict]:
    """Fit and gate one HMM per symbol; returns a row per symbol."""
    from data_engine.history import fetch_daily
    from strategies.hmm_regime import HMMRegimeDetector

    frames = frames if frames is not None else fetch_daily(symbols, days)
    rows = []
    for sym in symbols:
        df = frames.get(sym)
        if df is None or len(df) < 200:
            rows.append({"symbol": sym, "bars": 0 if df is None else len(df),
                         "passed": False, "reason": "not enough bars (need 200)"})
            continue
        det = HMMRegimeDetector(sym)
        det.fit(df)
        rows.append({"symbol": sym, "bars": len(df), **det.meta})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit gated HMM regime models")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols")
    parser.add_argument("--all", action="store_true", help="Every universe stock plus indices")
    parser.add_argument("--days", type=int, default=1095, help="Daily history (default 3 years)")
    args = parser.parse_args()

    from config.instruments import STOCK_UNIVERSE, get_nifty50_symbols
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.all:
        symbols = INDICES + list(STOCK_UNIVERSE)
    else:
        symbols = INDICES + get_nifty50_symbols()

    print(f"Fitting {len(symbols)} symbols on {args.days} days of daily bars...")
    rows = fit_regimes(symbols, args.days)
    print(f"\n{'symbol':<12}{'bars':>6}{'LL/bar HMM':>12}{'LL/bar 1-state':>16}{'avg run':>9}  result")
    for r in rows:
        if "ll_hmm" in r:
            print(f"{r['symbol']:<12}{r['bars']:>6}{r['ll_hmm']:>12.3f}{r['ll_base']:>16.3f}"
                  f"{r['mean_run']:>9.1f}  " + ("usable" if r["passed"] else r["reason"]))
        else:
            print(f"{r['symbol']:<12}{r['bars']:>6}{'':>37}  {r['reason']}")
    ok = sum(1 for r in rows if r.get("passed"))
    print(f"\n{ok}/{len(rows)} models usable; the rest use the ADX rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
