#!/usr/bin/env python
"""
Trade Journal — Query & Analysis Tool
======================================

Reads logs/trades.jsonl (live) and logs/paper_trades.jsonl (paper),
filters and aggregates by strategy, symbol, date range, or outcome.

Usage:
    python scripts/trade_journal.py                      # today's paper trades
    python scripts/trade_journal.py --days 7             # last 7 days
    python scripts/trade_journal.py --live               # live trades log
    python scripts/trade_journal.py --strategy ema_crossover
    python scripts/trade_journal.py --symbol RELIANCE
    python scripts/trade_journal.py --winners            # profitable only
    python scripts/trade_journal.py --by-strategy        # P&L per strategy
    python scripts/trade_journal.py --by-symbol          # P&L per symbol
    python scripts/trade_journal.py --export trades.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAPER_LOG = ROOT / "logs" / "paper_trades.jsonl"
LIVE_LOG  = ROOT / "logs" / "trades.jsonl"

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
DIM = "\033[2m"; C = "\033[96m"; E = "\033[0m"

def green(s):  return f"{G}{s}{E}"
def red(s):    return f"{R}{s}{E}"
def cyan(s):   return f"{C}{s}{E}"
def bold(s):   return f"{B}{s}{E}"
def dim(s):    return f"{DIM}{s}{E}"

def pnl_col(v: float, w: int = 12) -> str:
    s = f"₹{v:>+{w},.0f}"
    return green(s) if v > 0 else (red(s) if v < 0 else s)

def pct_col(v: float) -> str:
    s = f"{v:>+6.1f}%"
    return green(s) if v > 0 else (red(s) if v < 0 else s)


# ── Data loading ──────────────────────────────────────────────────────────────

def _load(log_file: Path, days: int | None,
          symbol: str | None, strategy: str | None,
          winners_only: bool) -> list[dict]:
    if not log_file.exists():
        return []

    records = []
    cutoff = (date.today() - timedelta(days=days)).isoformat() if days else None

    for line in log_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue

        # Only include close/trade records with P&L
        rec_type = r.get("type", "")
        if rec_type not in ("close", "order") and "pnl" not in r:
            continue
        if "pnl" not in r:
            continue

        # Date filter
        ts = r.get("ts", r.get("time", ""))
        if cutoff and ts[:10] < cutoff:
            continue

        # Symbol filter
        if symbol and r.get("symbol", "").upper() != symbol.upper():
            continue

        # Strategy filter
        if strategy and strategy.lower() not in r.get("strategy", "").lower():
            continue

        # Winners filter
        if winners_only and float(r.get("pnl", 0)) <= 0:
            continue

        records.append(r)

    return records


# ── Aggregation ───────────────────────────────────────────────────────────────

def _group(records: list[dict], key: str) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in records:
        k = r.get(key, "unknown")
        if k not in groups:
            groups[k] = {"name": k, "trades": 0, "wins": 0, "losses": 0,
                         "total_pnl": 0.0, "pnl_list": []}
        pnl = float(r.get("pnl", 0))
        g = groups[k]
        g["trades"] += 1
        g["total_pnl"] += pnl
        g["pnl_list"].append(pnl)
        if pnl > 0:
            g["wins"] += 1
        else:
            g["losses"] += 1

    result = []
    for g in groups.values():
        n = g["trades"]
        avg = g["total_pnl"] / n if n else 0.0
        g["win_rate"] = g["wins"] / n * 100 if n else 0.0
        g["avg_pnl"] = avg
        result.append(g)

    result.sort(key=lambda x: x["total_pnl"], reverse=True)
    return result


# ── Display ───────────────────────────────────────────────────────────────────

def _print_trades(records: list[dict], title: str) -> None:
    print(bold(f"\n  {title}  ({len(records)} trades)"))
    if not records:
        print(f"  {dim('No matching trades found.')}\n")
        return

    print(f"  {'Time':<20}  {'Symbol':<12}  {'Dir':<6}  {'Size':>6}  "
          f"{'Entry':>10}  {'Exit':>10}  {'P&L':>12}  Strategy")
    print("  " + "─" * 100)

    total_pnl = 0.0
    for r in records:
        ts      = r.get("ts", r.get("time", ""))[:19]
        sym     = r.get("symbol", "?")
        dirn    = r.get("direction", 0)
        dir_s   = green("LONG  ") if dirn == 1 else (red("SHORT ") if dirn == -1 else "  —   ")
        size    = int(float(r.get("size", r.get("quantity", 0))))
        entry   = float(r.get("entry_price", r.get("price", 0)))
        exit_p  = float(r.get("exit_price", entry))
        pnl     = float(r.get("pnl", 0))
        strat   = r.get("strategy", "—")[:22]
        total_pnl += pnl

        print(f"  {ts:<20}  {sym:<12}  {dir_s}  {size:>6}  "
              f"₹{entry:>8,.2f}  ₹{exit_p:>8,.2f}  {pnl_col(pnl)}  {strat}")

    print("  " + "─" * 100)
    wins = sum(1 for r in records if float(r.get("pnl", 0)) > 0)
    wr   = wins / len(records) * 100 if records else 0.0
    print(f"  TOTAL  {pnl_col(total_pnl)}   Win rate: {wr:.1f}%  ({wins}W / {len(records)-wins}L)\n")


def _print_grouped(groups: list[dict], group_label: str) -> None:
    if not groups:
        print(f"  {dim('No data.')}\n")
        return

    total_trades = sum(g["trades"] for g in groups)
    total_wins   = sum(g["wins"]   for g in groups)
    total_pnl    = sum(g["total_pnl"] for g in groups)

    print(f"  {group_label:<26}  {'Trades':>7}  {'Wins':>5}  "
          f"{'Losses':>7}  {'Win%':>6}  {'Total P&L':>13}  {'Avg P&L':>12}")
    print("  " + "─" * 92)

    for g in groups:
        name  = g["name"][:24]
        wr    = g["win_rate"]
        print(f"  {name:<26}  {g['trades']:>7}  {g['wins']:>5}  "
              f"{g['losses']:>7}  {wr:>5.1f}%  "
              f"{pnl_col(g['total_pnl'])}  {pnl_col(g['avg_pnl'], 10)}")

    print("  " + "─" * 92)
    overall_wr = total_wins / total_trades * 100 if total_trades else 0.0
    print(f"  {'TOTAL':<26}  {total_trades:>7}  {total_wins:>5}  "
          f"{total_trades-total_wins:>7}  {overall_wr:>5.1f}%  {pnl_col(total_pnl)}\n")


def _export_csv(records: list[dict], path: str) -> None:
    if not records:
        print(f"  {Y}No records to export.{E}")
        return
    fields = list({k for r in records for k in r.keys()})
    fields.sort()
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"  Exported {len(records)} records → {path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Trade journal query and analysis")
    parser.add_argument("--live",        action="store_true",
                        help="Query live trades (default: paper trades)")
    parser.add_argument("--days",        type=int, default=None,
                        help="Filter to last N days")
    parser.add_argument("--symbol",      help="Filter by symbol (e.g. RELIANCE)")
    parser.add_argument("--strategy",    help="Filter by strategy name (partial match)")
    parser.add_argument("--winners",     action="store_true",
                        help="Show only profitable trades")
    parser.add_argument("--by-strategy", action="store_true",
                        help="Group and aggregate by strategy")
    parser.add_argument("--by-symbol",   action="store_true",
                        help="Group and aggregate by symbol")
    parser.add_argument("--export",      metavar="FILE",
                        help="Export filtered records to CSV")
    args = parser.parse_args()

    log_file = LIVE_LOG if args.live else PAPER_LOG
    log_label = "live" if args.live else "paper"

    records = _load(
        log_file,
        days=args.days,
        symbol=args.symbol,
        strategy=args.strategy,
        winners_only=args.winners,
    )

    if args.export:
        _export_csv(records, args.export)
        return

    date_label = f"last {args.days} days" if args.days else "all time"
    sym_label  = f" | symbol={args.symbol}" if args.symbol else ""
    strat_label = f" | strategy={args.strategy}" if args.strategy else ""
    title = f"{log_label.title()} Trades  [{date_label}{sym_label}{strat_label}]"

    if args.by_strategy:
        print(bold(f"\n  Strategy Performance — {title}"))
        print("  " + "═" * 92)
        _print_grouped(_group(records, "strategy"), "Strategy")

    elif args.by_symbol:
        print(bold(f"\n  Symbol Performance — {title}"))
        print("  " + "═" * 92)
        _print_grouped(_group(records, "symbol"), "Symbol")

    else:
        _print_trades(records, title)


if __name__ == "__main__":
    main()
