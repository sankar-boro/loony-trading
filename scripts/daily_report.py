#!/usr/bin/env python
"""
Daily P&L Report
================

Reads data/daily_pnl.jsonl and prints a performance summary.

Usage:
    python scripts/daily_report.py              # today
    python scripts/daily_report.py --days 30    # last 30 days
    python scripts/daily_report.py --all        # entire history
    python scripts/daily_report.py --csv        # export to CSV
    python scripts/daily_report.py --days 7 --csv out.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DAILY_PNL_FILE = ROOT / "data" / "daily_pnl.jsonl"

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
DIM = "\033[2m"; E = "\033[0m"

def green(s):  return f"{G}{s}{E}"
def red(s):    return f"{R}{s}{E}"
def bold(s):   return f"{B}{s}{E}"
def dim(s):    return f"{DIM}{s}{E}"

def pnl_col(v: float, w: int = 12) -> str:
    s = f"₹{v:>+{w},.0f}"
    return green(s) if v > 0 else (red(s) if v < 0 else s)

def pct_col(v: float, w: int = 7) -> str:
    s = f"{v:>+{w}.2f}%"
    return green(s) if v > 0 else (red(s) if v < 0 else s)


def _load_records(days: int | None) -> list[dict]:
    if not DAILY_PNL_FILE.exists():
        return []
    records = []
    for line in DAILY_PNL_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            records.append(r)
        except Exception:
            continue

    if days is not None:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        records = [r for r in records if r.get("date", "") >= cutoff]

    records.sort(key=lambda r: r.get("date", ""))
    return records


def _sharpe(daily_pnls: list[float], capital: float) -> float:
    if len(daily_pnls) < 2:
        return 0.0
    import statistics
    returns = [p / capital for p in daily_pnls]
    avg = statistics.mean(returns)
    std = statistics.stdev(returns)
    if std == 0:
        return 0.0
    return (avg / std) * (252 ** 0.5)


def _print_report(records: list[dict]) -> None:
    if not records:
        print(f"\n  {dim('No records found.')}\n")
        return

    first_date = records[0].get("date", "?")
    last_date  = records[-1].get("date", "?")

    total_realised  = sum(r.get("realised", 0)  for r in records)
    total_trades    = sum(r.get("trades", 0)     for r in records)
    total_wins      = sum(r.get("wins", 0)       for r in records)
    total_losses    = sum(r.get("losses", 0)     for r in records)
    avg_daily_pnl   = total_realised / len(records) if records else 0.0
    win_rate        = total_wins / max(total_trades, 1) * 100
    max_dd          = max((r.get("max_drawdown_pct", 0) for r in records), default=0.0)
    best_day        = max(records, key=lambda r: r.get("realised", 0))
    worst_day       = min(records, key=lambda r: r.get("realised", 0))

    # Use 500_000 as default capital if not in records
    capital = records[0].get("capital", 500_000)
    sharpe  = _sharpe([r.get("realised", 0) for r in records], capital)

    print(bold(f"\n  Daily P&L Report  •  {first_date} → {last_date}  "
               f"({len(records)} trading days)"))
    print("  " + "═" * 80)

    print(f"\n  {'Period P&L:':<26} {pnl_col(total_realised)}")
    print(f"  {'Avg daily P&L:':<26} {pnl_col(avg_daily_pnl)}")
    print(f"  {'Total trades:':<26} {total_trades}")
    print(f"  {'Win rate:':<26} {win_rate:>7.1f}%  ({total_wins}W / {total_losses}L)")
    print(f"  {'Max drawdown (daily):':<26} {max_dd:>7.2f}%")
    print(f"  {'Sharpe ratio (ann.):':<26} {sharpe:>7.2f}")

    print(f"\n  Best day:   {best_day.get('date')}  "
          f"{pnl_col(best_day.get('realised', 0))}  "
          f"({best_day.get('trades', 0)} trades)")
    print(f"  Worst day:  {worst_day.get('date')}  "
          f"{pnl_col(worst_day.get('realised', 0))}  "
          f"({worst_day.get('trades', 0)} trades)")

    # ── Per-day table ─────────────────────────────────────────────────────────
    print(f"\n  {bold('Day-by-Day')}")
    print(f"  {'Date':<12}  {'Realised':>12}  {'Trades':>7}  {'Win%':>6}  "
          f"{'Max DD':>7}  Top Symbol")
    print("  " + "─" * 72)

    for r in records:
        dt     = r.get("date", "?")
        pnl    = r.get("realised", 0.0)
        trades = r.get("trades", 0)
        wr     = r.get("win_rate", 0.0)
        dd     = r.get("max_drawdown_pct", 0.0)
        sym    = r.get("top_symbol", "—")
        print(f"  {dt:<12}  {pnl_col(pnl)}  {trades:>7}  "
              f"{wr:>5.1f}%  {dd:>6.2f}%  {sym}")

    print("  " + "─" * 72)
    print(f"  {'TOTAL':<12}  {pnl_col(total_realised)}  {total_trades:>7}  "
          f"{win_rate:>5.1f}%\n")


def _export_csv(records: list[dict], path: str) -> None:
    import csv
    fields = ["date", "realised", "unrealised", "trades", "wins", "losses",
              "win_rate", "max_drawdown_pct", "top_symbol"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"  Exported {len(records)} records → {path}")


def main():
    parser = argparse.ArgumentParser(description="Daily P&L report from data/daily_pnl.jsonl")
    parser.add_argument("--days", type=int, default=None,
                        help="Show last N days (default: all)")
    parser.add_argument("--all",  action="store_true",
                        help="Show entire history (same as omitting --days)")
    parser.add_argument("--csv",  nargs="?", const="daily_pnl.csv", metavar="FILE",
                        help="Export to CSV (default: daily_pnl.csv)")
    args = parser.parse_args()

    days = None if args.all else (args.days if args.days else None)
    records = _load_records(days)

    if not records:
        print(f"\n  {Y}No data found in {DAILY_PNL_FILE}{E}")
        print(f"  Run a paper trade session first: python scripts/paper_trade.py\n")
        return

    if args.csv:
        _export_csv(records, args.csv)
    else:
        _print_report(records)


if __name__ == "__main__":
    main()
