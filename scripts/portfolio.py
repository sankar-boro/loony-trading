#!/usr/bin/env python
"""
Portfolio Dashboard
===================

Shows holdings, intraday positions, available funds, and P&L summary.
Requires a full trading token (not analytics-only).

Usage:
    python scripts/portfolio.py
    python scripts/portfolio.py --token eyJ0eXAi...
    python scripts/portfolio.py --holdings-only
    python scripts/portfolio.py --positions-only
    python scripts/portfolio.py --funds-only
    python scripts/portfolio.py --refresh 30       # auto-refresh every 30s
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "https://api.upstox.com/v2"

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
DIM = "\033[2m"; RESET = "\033[0m"; CLEAR = "\033[2J\033[H"

def green(s):  return f"{G}{s}{RESET}"
def red(s):    return f"{R}{s}{RESET}"
def yellow(s): return f"{Y}{s}{RESET}"
def bold(s):   return f"{B}{s}{RESET}"
def dim(s):    return f"{DIM}{s}{RESET}"
def pnl_str(v: float) -> str:
    s = f"₹{v:>+12,.2f}"
    return green(s) if v > 0 else (red(s) if v < 0 else s)


# ── env + token ───────────────────────────────────────────────────────────────

def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def _find_token(explicit=None) -> str:
    if explicit:
        return explicit
    t = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if t:
        return t
    tf = ROOT / "data" / "upstox_token.json"
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            age = (time.time() - d.get("obtained_at", 0)) / 3600
            if d.get("access_token") and age < 23:
                return d["access_token"]
        except Exception:
            pass
    return ""


def _get(token: str, path: str) -> tuple[int, dict]:
    import requests
    try:
        r = requests.get(
            f"{BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
        )
        return r.status_code, r.json()
    except Exception as e:
        return 0, {"error": str(e)}


# ── holdings ──────────────────────────────────────────────────────────────────

def show_holdings(token: str) -> float:
    code, resp = _get(token, "/portfolio/long-term-holdings")
    print(bold("\n  Long-Term Holdings  (Delivery / CNC)"))
    print("  " + "─" * 90)

    if code in (401, 403):
        print(f"  {yellow('Requires trading token')} — not available with analytics token")
        return 0.0
    if code != 200:
        print(f"  {red(f'Error: HTTP {code}')}")
        return 0.0

    holdings = resp.get("data", [])
    if not holdings:
        print("  No holdings found.")
        return 0.0

    print(f"  {'Symbol':<14}  {'Qty':>6}  {'Avg Cost':>12}  {'LTP':>12}  "
          f"{'Curr Value':>13}  {'P&L':>13}  {'P&L%':>7}")
    print("  " + "─" * 90)

    total_invested = 0.0
    total_current  = 0.0
    total_pnl      = 0.0

    for h in sorted(holdings, key=lambda x: x.get("trading_symbol", "")):
        sym    = h.get("trading_symbol", "")
        qty    = int(h.get("quantity", 0))
        avg    = float(h.get("average_price", 0))
        ltp    = float(h.get("last_price", 0))
        pnl    = float(h.get("pnl", 0))
        curr   = qty * ltp
        invest = qty * avg
        pct    = (pnl / invest * 100) if invest else 0

        total_invested += invest
        total_current  += curr
        total_pnl      += pnl

        pct_s = green(f"{pct:>+6.2f}%") if pct > 0 else (red(f"{pct:>+6.2f}%") if pct < 0 else f"{pct:>+6.2f}%")
        ltp_s = green(f"₹{ltp:>10,.2f}") if ltp > avg else red(f"₹{ltp:>10,.2f}")

        print(f"  {sym:<14}  {qty:>6,}  ₹{avg:>10,.2f}  {ltp_s}  "
              f"₹{curr:>11,.2f}  {pnl_str(pnl)}  {pct_s}")

    print("  " + "─" * 90)
    total_pct = ((total_current - total_invested) / total_invested * 100) if total_invested else 0
    pct_s = green(f"{total_pct:>+6.2f}%") if total_pct > 0 else red(f"{total_pct:>+6.2f}%")
    print(f"  {'TOTAL':<14}  {'':>6}  ₹{total_invested:>10,.2f}  {'':>12}  "
          f"₹{total_current:>11,.2f}  {pnl_str(total_pnl)}  {pct_s}")
    print(f"\n  {len(holdings)} holdings  •  "
          f"Invested: ₹{total_invested:,.2f}  •  Current: ₹{total_current:,.2f}")
    return total_pnl


# ── positions ─────────────────────────────────────────────────────────────────

def show_positions(token: str) -> float:
    code, resp = _get(token, "/portfolio/short-term-positions")
    print(bold("\n  Intraday Positions  (MIS / Short-Term)"))
    print("  " + "─" * 90)

    if code in (401, 403):
        print(f"  {yellow('Requires trading token')} — not available with analytics token")
        return 0.0
    if code != 200:
        print(f"  {red(f'Error: HTTP {code}')}")
        return 0.0

    positions = resp.get("data", [])
    open_pos  = [p for p in positions if int(p.get("quantity", 0)) != 0]
    closed    = [p for p in positions if int(p.get("quantity", 0)) == 0 and float(p.get("realised", 0)) != 0]

    if not positions:
        print("  No positions today.")
        return 0.0

    def _show_group(items: list, label: str):
        if not items:
            return
        print(f"\n  {dim(label)}")
        print(f"  {'Symbol':<14}  {'Product':<6}  {'Qty':>7}  {'Avg Buy':>12}  "
              f"{'LTP':>12}  {'Realised':>13}  {'Unrealised':>13}")
        print("  " + "─" * 90)
        for p in sorted(items, key=lambda x: x.get("trading_symbol", "")):
            sym    = p.get("trading_symbol", "")
            prod   = p.get("product", "")
            qty    = int(p.get("quantity", 0))
            buy_p  = float(p.get("buy_price", 0) or p.get("average_price", 0))
            ltp    = float(p.get("last_price", 0))
            real   = float(p.get("realised", 0))
            unreal = float(p.get("unrealised", 0))

            qty_s  = green(f"{qty:>+7,}") if qty > 0 else (red(f"{qty:>+7,}") if qty < 0 else f"{qty:>7,}")
            ltp_s  = green(f"₹{ltp:>10,.2f}") if ltp >= buy_p else red(f"₹{ltp:>10,.2f}")

            print(f"  {sym:<14}  {prod:<6}  {qty_s}  ₹{buy_p:>10,.2f}  {ltp_s}  "
                  f"{pnl_str(real)}  {pnl_str(unreal)}")

    _show_group(open_pos, "Open")
    _show_group(closed,   "Closed today")

    total_pnl = sum(float(p.get("realised", 0)) + float(p.get("unrealised", 0)) for p in positions)
    print(f"\n  {len(open_pos)} open  •  {len(closed)} closed  •  Total P&L: {pnl_str(total_pnl)}")
    return total_pnl


# ── funds ─────────────────────────────────────────────────────────────────────

def show_funds(token: str) -> None:
    code, resp = _get(token, "/user/get-funds-and-margin")
    print(bold("\n  Funds & Available Margin"))
    print("  " + "─" * 60)

    if code in (401, 403):
        print(f"  {yellow('Requires trading token')} — not available with analytics token")
        return
    if code != 200:
        print(f"  {red(f'Error: HTTP {code}')}")
        return

    data = resp.get("data", {})
    segments = data if isinstance(data, dict) else {}

    for seg_name, seg in segments.items():
        if not isinstance(seg, dict):
            continue
        print(f"\n  {bold(seg_name.upper())}")
        fields = [
            ("Available Cash",      seg.get("available_margin") or seg.get("equity", {}).get("available_margin")),
            ("Used Margin",         seg.get("used_margin")),
            ("Collateral",          seg.get("collateral")),
            ("Span Margin",         seg.get("span")),
            ("Exposure Margin",     seg.get("exposure")),
            ("Total Available",     seg.get("net") or seg.get("notional_cash")),
        ]
        for label, val in fields:
            if val is not None and val != 0:
                print(f"    {label:<22}  ₹{float(val):>12,.2f}")

    print()


# ── main ──────────────────────────────────────────────────────────────────────

def _run(token: str, args) -> None:
    from datetime import datetime
    print(CLEAR, end="")
    print(bold(f"\n  Portfolio Dashboard  •  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    print("  " + "═" * 90)

    pnl_holdings  = 0.0
    pnl_positions = 0.0

    if not args.positions_only and not args.funds_only:
        pnl_holdings = show_holdings(token)

    if not args.holdings_only and not args.funds_only:
        pnl_positions = show_positions(token)

    if not args.holdings_only and not args.positions_only:
        show_funds(token)

    if not args.funds_only:
        total = pnl_holdings + pnl_positions
        print(bold("\n  ── Overall P&L Summary ──────────────────────────────"))
        print(f"    Holdings unrealised P&L:   {pnl_str(pnl_holdings)}")
        print(f"    Today's positions P&L:     {pnl_str(pnl_positions)}")
        print(f"    Total:                     {pnl_str(total)}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Portfolio dashboard")
    parser.add_argument("--token",          help="Explicit access token")
    parser.add_argument("--holdings-only",  action="store_true")
    parser.add_argument("--positions-only", action="store_true")
    parser.add_argument("--funds-only",     action="store_true")
    parser.add_argument("--refresh",        type=int, default=0,
                        help="Auto-refresh interval in seconds (0=one-shot)")
    args = parser.parse_args()

    _load_env()
    token = _find_token(args.token)
    if not token:
        print(f"{R}No token found.{RESET}  Run: python scripts/upstox_login.py")
        sys.exit(1)

    if args.refresh > 0:
        try:
            while True:
                _run(token, args)
                print(f"  {dim(f'Auto-refreshing in {args.refresh}s  •  Ctrl+C to exit')}")
                time.sleep(args.refresh)
        except KeyboardInterrupt:
            print(f"\n  {dim('Exiting.')}\n")
    else:
        _run(token, args)


if __name__ == "__main__":
    main()
