#!/usr/bin/env python3
"""
Record what happened after past composite signals, then print how they did.

    python scripts/evaluate_signals.py               # update outcomes, report last 90 days
    python scripts/evaluate_signals.py --days 30 --report-only

The scheduler runs the update every weekday at 16:30 IST (signal_outcomes job).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate composite signal outcomes")
    parser.add_argument("--days", type=int, default=90, help="Report window (default 90)")
    parser.add_argument("--report-only", action="store_true", help="Skip the update")
    args = parser.parse_args()

    from db.base import session_scope
    from signals.outcomes import performance, update_outcomes

    with session_scope() as db:
        if not args.report_only:
            from data_engine.history import fetch_daily
            print("Updating outcomes:", update_outcomes(db, fetch_daily))
        p = performance(db, days=args.days)

    print(f"\nLast {p['days']} days: {p['evaluated']} signals evaluated, {p['complete']} complete")
    b = p["baseline"]
    print(f"Baseline (all evaluated signals, raw): 1d {b['ret_1d']}%  5d {b['ret_5d']}%  20d {b['ret_20d']}%\n")
    print(f"{'direction':<11}{'n':>6}{'avg 5d':>9}{'hit 5d':>8}{'excess 5d':>11}{'avg 20d':>9}  setups (target/stop/expired)")
    for d in p["by_direction"]:
        if not d["count"]:
            continue
        st = d["setups"]
        fmt = lambda v, suf="": "—" if v is None else f"{v:.2f}{suf}"
        print(f"{d['direction']:<11}{d['count']:>6}{fmt(d['avg_5d'], '%'):>9}{fmt(d['hit_5d'], '%'):>8}"
              f"{fmt(d['excess_5d'], '%'):>11}{fmt(d['avg_20d'], '%'):>9}  "
              f"{st['target']}/{st['stop']}/{st['expired']}")
    if p["by_score"]:
        print("\nBullish + bearish by score (direction-adjusted 5-day return):")
        for r in p["by_score"]:
            print(f"  {r['band']:<8} n={r['count']:<5} avg {r['avg_5d']}%  hit {r['hit_5d']}%")
    print("\nComponent vs direction-adjusted 5-day return (correlation):")
    print("  " + "  ".join(f"{c['component']} {c['corr_5d']}" for c in p["components"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
