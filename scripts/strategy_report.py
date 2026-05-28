#!/usr/bin/env python
"""
Strategy Performance Report
============================

Reads logs/paper_trades.jsonl (closed trades from paper_trade.py) and shows
a breakdown by strategy: P&L, win rate, trade count, avg win/loss, and
Sharpe contribution.

Usage:
    python scripts/strategy_report.py
    python scripts/strategy_report.py --file logs/paper_trades.jsonl
    python scripts/strategy_report.py --days 30        # last 30 days only
    python scripts/strategy_report.py --min-trades 3   # only strategies with ≥3 trades
    python scripts/strategy_report.py --csv            # CSV output
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

G   = "\033[92m"; R  = "\033[91m"; Y  = "\033[93m"
B   = "\033[1m";  DIM = "\033[2m"; E  = "\033[0m"


def _load_trades(path: Path, days: int | None = None) -> list[dict]:
    if not path.exists():
        print(f"{R}Trade log not found: {path}{E}")
        print("Run a paper trading session first: python scripts/paper_trade.py")
        sys.exit(1)

    cutoff = None
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    trades = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            t = json.loads(line)
            if t.get("type") != "close" and "exit_price" not in t:
                continue   # skip open/signal entries if mixed in
            if cutoff and t.get("ts", t.get("exit_time", "")) < cutoff:
                continue
            trades.append(t)
        except Exception:
            pass

    return trades


def _compute_stats(trades: list[dict]) -> dict[str, dict]:
    by_strat: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        strategy = t.get("strategy", "unknown")
        pnl = float(t.get("pnl", 0))
        by_strat[strategy].append(pnl)

    stats = {}
    for strat, pnls in by_strat.items():
        n = len(pnls)
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total  = sum(pnls)
        avg    = total / n if n else 0
        wr     = len(wins) / n * 100 if n else 0
        avg_w  = sum(wins) / len(wins) if wins else 0
        avg_l  = sum(losses) / len(losses) if losses else 0
        pf     = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

        # Simple Sharpe (annualised from trade returns, ~250 trades/year assumption)
        import statistics, math
        if n >= 3:
            mean_r = statistics.mean(pnls)
            std_r  = statistics.stdev(pnls) if n > 1 else 0
            sharpe = (mean_r / std_r * math.sqrt(n)) if std_r > 0 else 0
        else:
            sharpe = 0.0

        stats[strat] = {
            "n":       n,
            "total":   total,
            "avg":     avg,
            "wins":    len(wins),
            "losses":  len(losses),
            "win_rate": wr,
            "avg_win": avg_w,
            "avg_loss": avg_l,
            "pf":      pf,
            "sharpe":  sharpe,
        }
    return stats


def _format_pnl(v: float) -> str:
    c = G if v >= 0 else R
    return f"{c}₹{v:>+10,.0f}{E}"


def _format_pct(v: float) -> str:
    c = G if v >= 50 else (Y if v >= 35 else R)
    return f"{c}{v:>5.1f}%{E}"


def main():
    parser = argparse.ArgumentParser(description="Per-strategy performance report")
    parser.add_argument("--file",       default="logs/paper_trades.jsonl",
                        help="Trade log file (default: logs/paper_trades.jsonl)")
    parser.add_argument("--days",       type=int, default=0,
                        help="Limit to last N calendar days (default: all)")
    parser.add_argument("--min-trades", type=int, default=1,
                        help="Minimum trades to include a strategy (default: 1)")
    parser.add_argument("--sort",       default="total",
                        choices=["total", "sharpe", "win_rate", "trades"],
                        help="Sort column (default: total)")
    parser.add_argument("--csv",        action="store_true",
                        help="Output as CSV")
    args = parser.parse_args()

    path = ROOT / args.file if not Path(args.file).is_absolute() else Path(args.file)
    trades = _load_trades(path, args.days or None)

    if not trades:
        print(f"{Y}No closed trades found in {path}{E}")
        sys.exit(0)

    stats = _compute_stats(trades)

    # Filter and sort
    stats = {k: v for k, v in stats.items() if v["n"] >= args.min_trades}
    sort_key = {
        "total":    lambda kv: kv[1]["total"],
        "sharpe":   lambda kv: kv[1]["sharpe"],
        "win_rate": lambda kv: kv[1]["win_rate"],
        "trades":   lambda kv: kv[1]["n"],
    }[args.sort]
    ordered = sorted(stats.items(), key=sort_key, reverse=True)

    if args.csv:
        print("strategy,trades,total_pnl,win_rate,avg_win,avg_loss,profit_factor,sharpe")
        for strat, s in ordered:
            print(f"{strat},{s['n']},{s['total']:.2f},{s['win_rate']:.1f},"
                  f"{s['avg_win']:.2f},{s['avg_loss']:.2f},{s['pf']:.2f},{s['sharpe']:.3f}")
        return

    # Pretty-print
    period = f"last {args.days} days" if args.days else "all time"
    print(f"\n{B}  Strategy Performance Report{E}  "
          f"{DIM}({len(trades)} trades · {period} · sorted by {args.sort}){E}\n")

    hdr = (f"  {'Strategy':<26}  {'Trades':>6}  {'Total P&L':>12}  "
           f"{'WinRate':>8}  {'AvgWin':>10}  {'AvgLoss':>10}  "
           f"{'PF':>6}  {'Sharpe':>7}")
    print(hdr)
    print("  " + "─" * 100)

    total_pnl = 0
    total_trades = 0
    all_pnls: list[float] = []

    for strat, s in ordered:
        pf_s   = f"{s['pf']:>6.2f}" if s["pf"] != float("inf") else f"{'∞':>6}"
        sharpe = s["sharpe"]
        sh_c   = G if sharpe >= 1 else (Y if sharpe >= 0 else R)
        print(
            f"  {strat:<26}  {s['n']:>6}  "
            f"{_format_pnl(s['total'])}  "
            f"{_format_pct(s['win_rate'])}  "
            f"{_format_pnl(s['avg_win'])}  "
            f"{_format_pnl(s['avg_loss'])}  "
            f"{pf_s}  "
            f"{sh_c}{sharpe:>7.3f}{E}"
        )
        total_pnl    += s["total"]
        total_trades += s["n"]
        all_pnls.extend([0.0] * (s["n"] - len(all_pnls)))   # placeholder for portfolio Sharpe

    print("  " + "─" * 100)
    print(f"\n  {B}Total{E}  {total_trades} trades  •  {_format_pnl(total_pnl)}")

    # Overall win rate
    all_wins = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
    ov_wr = all_wins / len(trades) * 100 if trades else 0
    print(f"  Overall win rate: {_format_pct(ov_wr)}  "
          f"({all_wins}W / {len(trades)-all_wins}L)")

    # Best / worst trade
    best  = max(trades, key=lambda t: float(t.get("pnl", 0)), default=None)
    worst = min(trades, key=lambda t: float(t.get("pnl", 0)), default=None)
    if best:
        print(f"  Best trade:  {best.get('symbol', '?')} {_format_pnl(float(best.get('pnl',0)))} "
              f"  [{best.get('strategy','?')}]")
    if worst:
        print(f"  Worst trade: {worst.get('symbol', '?')} {_format_pnl(float(worst.get('pnl',0)))} "
              f"  [{worst.get('strategy','?')}]")

    # Symbol breakdown
    sym_pnl: dict[str, float] = defaultdict(float)
    sym_cnt: dict[str, int]   = defaultdict(int)
    for t in trades:
        sym_pnl[t.get("symbol", "?")] += float(t.get("pnl", 0))
        sym_cnt[t.get("symbol", "?")] += 1

    top_syms = sorted(sym_pnl.items(), key=lambda x: x[1], reverse=True)[:8]
    if top_syms:
        print(f"\n  {B}Top symbols by P&L:{E}")
        for sym, pnl in top_syms:
            bar_w = int(abs(pnl) / (max(abs(p) for _, p in top_syms) or 1) * 20)
            bar_c = G if pnl >= 0 else R
            print(f"    {sym:<14}  {_format_pnl(pnl)}  "
                  f"{bar_c}{'█' * bar_w}{'░' * (20 - bar_w)}{E}  "
                  f"{DIM}{sym_cnt[sym]} trades{E}")

    print()


if __name__ == "__main__":
    main()
