#!/usr/bin/env python
"""
Market Watch — Live Terminal Dashboard
=======================================

Displays live prices for a configurable watchlist with auto-refresh.
Uses full-quote endpoint for OHLC + depth; LTP endpoint for rapid polling.

Usage:
    python scripts/market_watch.py
    python scripts/market_watch.py --interval 3
    python scripts/market_watch.py --instruments "RELIANCE,TCS,INFY"
    python scripts/market_watch.py --indices-only
    python scripts/market_watch.py --token eyJ0eXAi...
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "https://api.upstox.com/v2"

# ── colour / format helpers ───────────────────────────────────────────────────
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
DIM = "\033[2m"; RESET = "\033[0m"; CLEAR = "\033[2J\033[H"

def green(s):  return f"{G}{s}{RESET}"
def red(s):    return f"{R}{s}{RESET}"
def yellow(s): return f"{Y}{s}{RESET}"
def bold(s):   return f"{B}{s}{RESET}"
def dim(s):    return f"{DIM}{s}{RESET}"

def clr(value: float | None, base: float | None) -> str:
    """Return coloured string based on up/down vs base."""
    if value is None:
        return dim("  —  ")
    if base is None:
        return f"{value:>10,.2f}"
    if value > base:
        return green(f"{value:>10,.2f}")
    if value < base:
        return red(f"{value:>10,.2f}")
    return f"{value:>10,.2f}"

def clr_pct(pct: float | None) -> str:
    if pct is None:
        return dim("    —  ")
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
    s = f"{arrow}{abs(pct):>5.2f}%"
    if pct > 0:   return green(f"{s:>8}")
    if pct < 0:   return red(f"{s:>8}")
    return f"{s:>8}"


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
    import json
    if explicit:
        return explicit
    for var in ("UPSTOX_ACCESS_TOKEN", "UPSTOX_ANALYTICS_API_KEY"):
        t = os.environ.get(var, "").strip()
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


def _enc(k: str) -> str:
    return k.replace("|", "%7C").replace(" ", "%20")


# ── API calls ─────────────────────────────────────────────────────────────────

def _get_ltp(token: str, instrument_keys: list[str]) -> dict:
    import requests
    keys = ",".join(_enc(k) for k in instrument_keys)
    try:
        r = requests.get(
            f"{BASE}/market-quote/ltp?instrument_key={keys}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
        if r.status_code == 200:
            return r.json().get("data", {})
    except Exception:
        pass
    return {}


def _get_quotes(token: str, instrument_keys: list[str]) -> dict:
    import requests
    keys = ",".join(_enc(k) for k in instrument_keys)
    try:
        r = requests.get(
            f"{BASE}/market-quote/quotes?instrument_key={keys}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("data", {})
    except Exception:
        pass
    return {}


def _market_status(token: str) -> str:
    import requests
    try:
        r = requests.get(
            f"{BASE}/market/status?exchange=NSE",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=5,
        )
        if r.status_code == 200:
            d = r.json().get("data", {})
            markets = d if isinstance(d, list) else d.get("markets", [])
            for m in (markets if isinstance(markets, list) else []):
                if "NSE" in str(m.get("exchange", "")):
                    state = m.get("market_status", "")
                    return green("NSE Open") if "open" in state.lower() else red(f"NSE {state}")
    except Exception:
        pass
    return dim("status unknown")


# ── default watchlist ─────────────────────────────────────────────────────────

DEFAULT_INDICES = [
    ("NIFTY 50",       "NSE_INDEX|Nifty 50"),
    ("BANK NIFTY",     "NSE_INDEX|Nifty Bank"),
    ("NIFTY IT",       "NSE_INDEX|Nifty IT"),
    ("INDIA VIX",      "NSE_INDEX|India VIX"),
    ("NIFTY MIDCAP",   "NSE_INDEX|NIFTY MIDCAP 150"),
]

DEFAULT_EQUITIES = [
    ("RELIANCE",  "NSE_EQ|INE002A01018"),
    ("TCS",       "NSE_EQ|INE467B01029"),
    ("HDFCBANK",  "NSE_EQ|INE040A01034"),
    ("INFY",      "NSE_EQ|INE009A01021"),
    ("ICICIBANK", "NSE_EQ|INE090A01021"),
    ("SBIN",      "NSE_EQ|INE062A01020"),
    ("WIPRO",     "NSE_EQ|INE075A01022"),
    ("ADANIENT",  "NSE_EQ|INE423A01024"),
]

EQUITY_ISIN = {
    "RELIANCE": "INE002A01018", "TCS": "INE467B01029",
    "HDFCBANK": "INE040A01034", "INFY": "INE009A01021",
    "ICICIBANK": "INE090A01021", "SBIN": "INE062A01020",
    "WIPRO": "INE075A01022", "ADANIENT": "INE423A01024",
    "BAJFINANCE": "INE296A01024", "KOTAKBANK": "INE237A01028",
    "HINDUNILVR": "INE030A01027", "AXISBANK": "INE238A01034",
    "LT": "INE018A01030", "MARUTI": "INE585B01010",
    "SUNPHARMA": "INE044A01036",
}


def _parse_custom_instruments(symbols: str) -> list[tuple[str, str]]:
    result = []
    for sym in symbols.upper().split(","):
        sym = sym.strip()
        if not sym:
            continue
        isin = EQUITY_ISIN.get(sym)
        if isin:
            result.append((sym, f"NSE_EQ|{isin}"))
        else:
            print(f"  [!] Unknown symbol '{sym}' — skipping. Add its ISIN to EQUITY_ISIN dict.")
    return result


# ── rendering ─────────────────────────────────────────────────────────────────

def _render(instruments: list[tuple[str, str]], data: dict, prev_data: dict, status: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    print(CLEAR, end="")
    print(bold(f"  Market Watch  •  {now}  •  {status}"))
    print()
    print(f"  {'Symbol':<14}  {'LTP':>11}  {'Change':>9}  {'Change%':>8}  "
          f"{'Open':>10}  {'High':>10}  {'Low':>10}  {'Volume':>12}")
    print("  " + "─" * 97)

    for name, key in instruments:
        resp_key = key.replace("|", ":")
        entry = data.get(resp_key, {})
        prev  = prev_data.get(resp_key, {})

        ltp        = entry.get("last_price") or (entry.get("ohlc", {}) or {}).get("close")
        prev_close = entry.get("close_price") or entry.get("prev_close") or (prev.get("last_price") if prev else None)
        ohlc       = entry.get("ohlc", {}) or {}
        o = ohlc.get("open");  h = ohlc.get("high")
        lo = ohlc.get("low");  vol = entry.get("volume") or entry.get("total_buy_quantity")

        chg = (ltp - prev_close) if (ltp is not None and prev_close) else None
        pct = (chg / prev_close * 100) if (chg is not None and prev_close) else None

        ltp_s  = clr(ltp, prev_close)
        chg_s  = (green(f"{chg:>+10,.2f}") if chg and chg > 0 else
                  red(f"{chg:>+10,.2f}") if chg and chg < 0 else dim(f"{'—':>10}"))
        pct_s  = clr_pct(pct)
        o_s    = f"{o:>10,.2f}"   if o   else dim(f"{'—':>10}")
        h_s    = green(f"{h:>10,.2f}") if h else dim(f"{'—':>10}")
        lo_s   = red(f"{lo:>10,.2f}") if lo else dim(f"{'—':>10}")
        vol_s  = f"{int(vol):>12,}" if vol else dim(f"{'—':>12}")

        print(f"  {name:<14}  {ltp_s}  {chg_s}  {pct_s}  {o_s}  {h_s}  {lo_s}  {vol_s}")

    print()


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Live market price dashboard")
    parser.add_argument("--token", help="Upstox access token")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Refresh interval in seconds (default: 5)")
    parser.add_argument("--instruments", help="Comma-separated symbols: RELIANCE,TCS,INFY")
    parser.add_argument("--indices-only", action="store_true", help="Show indices only")
    parser.add_argument("--no-clear", action="store_true",
                        help="Don't clear screen on refresh (pipe-friendly)")
    args = parser.parse_args()

    _load_env()
    token = _find_token(args.token)
    if not token:
        print(f"{R}No token found.{RESET}  Run: python scripts/upstox_login.py")
        sys.exit(1)

    # Build watchlist
    if args.instruments:
        instruments = _parse_custom_instruments(args.instruments)
        if not instruments:
            print("No valid instruments found."); sys.exit(1)
    elif args.indices_only:
        instruments = DEFAULT_INDICES
    else:
        instruments = DEFAULT_INDICES + DEFAULT_EQUITIES

    keys = [k for _, k in instruments]

    print(bold("\n  Market Watch starting..."))
    print(f"  Watching {len(instruments)} instruments  •  refresh every {args.interval}s")
    print(f"  Press Ctrl+C to exit\n")
    time.sleep(0.5)

    prev_data: dict = {}
    global CLEAR
    if args.no_clear:
        CLEAR = "\n" + "─" * 100 + "\n"

    try:
        while True:
            t0 = time.time()
            from utils.timeutils import is_market_session, next_market_open, minutes_to_market_close
            if not is_market_session():
                nxt = next_market_open()
                status = yellow(f"Market closed  •  Next open: {nxt.strftime('%a %H:%M IST')}")
            else:
                mins_left = minutes_to_market_close()
                raw_status = _market_status(token)
                if mins_left <= 30:
                    status = f"{raw_status}  {yellow(f'Closes in {mins_left} min')}"
                else:
                    status = raw_status
            data = _get_quotes(token, keys)
            if not data:
                data = {k.replace("|", ":"): {"last_price": v.get("last_price")}
                        for k, v in _get_ltp(token, keys).items()}
            _render(instruments, data, prev_data, status)

            elapsed = time.time() - t0
            remaining = max(0.1, args.interval - elapsed)

            for i in range(int(remaining * 10)):
                left = remaining - i * 0.1
                print(f"\r  {dim(f'Refreshing in {left:.1f}s  •  Ctrl+C to exit')}  ", end="", flush=True)
                time.sleep(0.1)

            prev_data = dict(data)

    except KeyboardInterrupt:
        print(f"\n\n  {dim('Exiting market watch.')}\n")


if __name__ == "__main__":
    main()
