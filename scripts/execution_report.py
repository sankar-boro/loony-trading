#!/usr/bin/env python3
"""
Execution quality: fill rate and slippage against the decision price, by
entry/exit, order type, strategy, hour and limit-order chases — from
logs/executions.jsonl, which the executor writes for every order.

    python scripts/execution_report.py                 # last 30 days, both modes
    python scripts/execution_report.py --days 7 --mode live
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _row(label: str, s: dict) -> str:
    f = lambda v, suf="": "—" if v is None else f"{v}{suf}"
    return (f"{label:<22}{s['orders']:>7}{f(s['fill_rate_pct'], '%'):>9}{f(s['avg_slippage_bps']):>10}"
            f"{f(s['median_slippage_bps']):>9}{f(s['p90_slippage_bps']):>8}{s['slippage_cost']:>12,.0f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Execution quality report")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--mode", choices=["paper", "live"], default=None)
    args = parser.parse_args()

    from analytics.execution_quality import EXECUTION_LOG, load, report
    r = report(load(EXECUTION_LOG), days=args.days, mode=args.mode)
    if not r["overall"]["orders"]:
        print(f"No orders in {EXECUTION_LOG} for the last {args.days} days.")
        return 0
    head = f"{'':<22}{'orders':>7}{'filled':>9}{'avg bps':>10}{'median':>9}{'p90':>8}{'cost ₹':>12}"
    print(f"Execution quality, last {args.days} days ({args.mode or 'paper + live'}); "
          "slippage vs decision price, + = cost\n")
    print(head)
    print(_row("all", r["overall"]))
    print("outcomes: " + ", ".join(f"{k} {v}" for k, v in r["outcomes"].items()))
    for title, key in (("by entry/exit", "by_kind"), ("by order type", "by_order_type"),
                       ("by strategy", "by_strategy"), ("by hour (IST)", "by_hour"),
                       ("limit orders by chases", "by_chases")):
        print(f"\n{title}")
        for g in r[key]:
            print(_row("  " + g["key"], g))
    return 0


if __name__ == "__main__":
    sys.exit(main())
