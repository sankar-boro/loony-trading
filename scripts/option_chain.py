#!/usr/bin/env python
"""
Option Chain Viewer
====================

Displays a formatted option chain (calls + puts side-by-side) for any
Nifty/BankNifty/stock with ATM strike highlighted and Greeks computed.

Usage:
    python scripts/option_chain.py                        # Nifty 50, next expiry
    python scripts/option_chain.py --symbol "Nifty Bank"
    python scripts/option_chain.py --expiry 2026-07-31
    python scripts/option_chain.py --strikes 10           # ±10 strikes around ATM
    python scripts/option_chain.py --refresh 30           # auto-refresh
    python scripts/option_chain.py --token eyJ0eXAi...
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "https://api.upstox.com/v2"

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
DIM = "\033[2m"; CYAN = "\033[96m"; RESET = "\033[0m"; CLEAR = "\033[2J\033[H"

def green(s):  return f"{G}{s}{RESET}"
def red(s):    return f"{R}{s}{RESET}"
def yellow(s): return f"{Y}{s}{RESET}"
def bold(s):   return f"{B}{s}{RESET}"
def dim(s):    return f"{DIM}{s}{RESET}"
def cyan(s):   return f"{CYAN}{s}{RESET}"


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
    for var in ("UPSTOX_ACCESS_TOKEN", "UPSTOX_ANALYTICS_API_KEY"):
        t = os.environ.get(var, "").strip()
        if t:
            return t
    tf = ROOT / "data" / "upstox_token.json"
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            from data_engine.upstox.auth import token_hours_left
            if d.get("access_token") and token_hours_left(d.get("obtained_at", 0)) > 0:
                return d["access_token"]
        except Exception:
            pass
    return ""


def _enc(k: str) -> str:
    return k.replace("|", "%7C").replace(" ", "%20")


def _get(token: str, path: str) -> tuple[int, dict]:
    import requests
    try:
        r = requests.get(
            f"{BASE}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
        )
        return r.status_code, (r.json() if r.content else {})
    except Exception as e:
        return 0, {}


# ── expiry helpers ────────────────────────────────────────────────────────────

def _next_monthly_expiry(from_date: date | None = None) -> str:
    """Last Thursday of the current or next month."""
    d = from_date or date.today()
    # move to next month if we're past ~25th
    if d.day >= 25:
        d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    else:
        d = d.replace(day=1)
    # last day of that month
    next_m = (d + timedelta(days=32)).replace(day=1)
    last_day = next_m - timedelta(days=1)
    # walk back to Thursday (weekday 3)
    while last_day.weekday() != 3:
        last_day -= timedelta(days=1)
    return last_day.isoformat()


def _next_weekly_expiry() -> str:
    """Next Thursday from today."""
    d = date.today()
    days_to_thu = (3 - d.weekday()) % 7
    if days_to_thu == 0:
        days_to_thu = 7
    return (d + timedelta(days=days_to_thu)).isoformat()


def _list_expiries(token: str, instrument_key: str) -> list[str]:
    """Fetch available expiries for an option chain."""
    code, resp = _get(token, f"/option/contract?instrument_key={_enc(instrument_key)}")
    if code == 200:
        data = resp.get("data", [])
        if isinstance(data, list):
            expiries = sorted({d.get("expiry", "") for d in data if d.get("expiry")})
            return expiries
    return []


# ── Black-Scholes IV (Newton-Raphson) ────────────────────────────────────────

def _bs_price(S, K, T, r, sigma, opt="call") -> float:
    if T <= 0 or sigma <= 0:
        return max(0, (S - K) if opt == "call" else (K - S))
    from math import log, sqrt, exp
    try:
        from scipy.stats import norm
        d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
        d2 = d1 - sigma * sqrt(T)
        if opt == "call":
            return S * norm.cdf(d1) - K * exp(-r * T) * norm.cdf(d2)
        return K * exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    except ImportError:
        # fallback: rough approximation without scipy
        return max(0.01, abs(S - K) * 0.1)


def _implied_vol(S, K, T, r, market_price, opt="call") -> float | None:
    if T <= 0 or market_price <= 0:
        return None
    lo, hi = 0.001, 5.0
    for _ in range(50):
        mid = (lo + hi) / 2
        price = _bs_price(S, K, T, r, mid, opt)
        if abs(price - market_price) < 0.01:
            return mid
        if price < market_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _delta(S, K, T, r, sigma, opt="call") -> float:
    if T <= 0 or sigma <= 0:
        return 0
    try:
        from math import log, sqrt
        from scipy.stats import norm
        d1 = (log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt(T))
        return norm.cdf(d1) if opt == "call" else norm.cdf(d1) - 1
    except Exception:
        return 0.5 if opt == "call" else -0.5


# ── option chain rendering ────────────────────────────────────────────────────

def _render_chain(token: str, symbol_name: str, instrument_key: str,
                  expiry: str, n_strikes: int, spot: float) -> None:
    code, resp = _get(
        token,
        f"/option/chain?instrument_key={_enc(instrument_key)}&expiry_date={expiry}"
    )

    if code == 404 or code == 400:
        print(f"\n  {yellow(f'Expiry {expiry} not found for {symbol_name}.')}")
        print(f"  Try: python scripts/option_chain.py --expiry <YYYY-MM-DD>")
        return
    if code != 200:
        print(f"\n  {red(f'Option chain fetch failed: HTTP {code}')}")
        return

    chain_raw = resp.get("data", [])
    if not chain_raw:
        print(f"\n  {yellow('No option chain data returned.')}  Expiry may not exist.")
        return

    # Normalise: Upstox may return list or dict
    if isinstance(chain_raw, dict):
        chain_raw = list(chain_raw.values())

    # Build dict keyed by strike
    chain: dict[float, dict] = {}
    for item in chain_raw:
        strike = float(item.get("strike_price", 0))
        chain[strike] = item

    if not chain:
        print(f"  {yellow('Empty chain.')}")
        return

    strikes_sorted = sorted(chain.keys())
    atm = min(strikes_sorted, key=lambda s: abs(s - spot))

    # Limit to n_strikes around ATM
    atm_idx = strikes_sorted.index(atm)
    lo_idx  = max(0, atm_idx - n_strikes)
    hi_idx  = min(len(strikes_sorted) - 1, atm_idx + n_strikes)
    display_strikes = strikes_sorted[lo_idx:hi_idx + 1]

    # Days to expiry
    exp_date = date.fromisoformat(expiry)
    dte = max(0, (exp_date - date.today()).days)
    T = dte / 365

    from datetime import datetime
    now_str = datetime.now().strftime("%H:%M:%S")

    print(CLEAR, end="")
    print(bold(f"\n  {symbol_name} Option Chain  •  Expiry: {expiry}  •  "
               f"DTE: {dte}d  •  Spot: ₹{spot:,.2f}  •  ATM: ₹{atm:,.2f}  •  {now_str}"))
    print()

    # Header
    cw = 9
    print(f"  {'─'*50}  {'Strike':^10}  {'─'*50}")
    print(f"  {'OI':>{cw}}  {'Chg OI':>{cw}}  {'Vol':>{cw}}  {'IV':>6}  {'Delta':>6}  {'LTP':>{cw}}  "
          f"  {'Strike':^10}  "
          f"  {'LTP':>{cw}}  {'Delta':>6}  {'IV':>6}  {'Vol':>{cw}}  {'Chg OI':>{cw}}  {'OI':>{cw}}")
    print(f"  {'─'*50}  {'──────────':^10}  {'─'*50}")

    for strike in display_strikes:
        item   = chain[strike]
        is_atm = (strike == atm)

        call = item.get("call_options", item.get("ce", {})) or {}
        put  = item.get("put_options",  item.get("pe", {})) or {}

        def _market(opt: dict) -> dict:
            return opt.get("market_data", opt) or {}

        cm = _market(call); pm = _market(put)

        c_ltp    = float(cm.get("ltp", 0) or 0)
        c_oi     = int(cm.get("oi", 0) or cm.get("open_interest", 0) or 0)
        c_chg_oi = int(cm.get("change_oi", 0) or 0)
        c_vol    = int(cm.get("volume", 0) or 0)

        p_ltp    = float(pm.get("ltp", 0) or 0)
        p_oi     = int(pm.get("oi", 0) or pm.get("open_interest", 0) or 0)
        p_chg_oi = int(pm.get("change_oi", 0) or 0)
        p_vol    = int(pm.get("volume", 0) or 0)

        c_iv = _implied_vol(spot, strike, T, 0.065, c_ltp, "call") if c_ltp > 0 else None
        p_iv = _implied_vol(spot, strike, T, 0.065, p_ltp, "put")  if p_ltp > 0 else None

        c_delta = _delta(spot, strike, T, 0.065, c_iv or 0.15, "call") if c_iv else None
        p_delta = _delta(spot, strike, T, 0.065, p_iv or 0.15, "put")  if p_iv else None

        # Format
        def _oi_s(v):   return f"{v:>{cw},}" if v else dim(f"{'—':>{cw}}")
        def _ltp_s(v):  return f"₹{v:>{cw-1},.1f}" if v else dim(f"{'—':>{cw}}")
        def _iv_s(v):   return f"{v*100:>5.1f}%" if v else dim(f"{'—':>6}")
        def _dlt_s(v):  return f"{v:>+5.3f}" if v else dim(f"{'—':>6}")
        def _chg_s(v):
            if not v: return dim(f"{'—':>{cw}}")
            s = f"{v:>+{cw},}"
            return green(s) if v > 0 else red(s)

        strike_s = cyan(f"▶ {strike:>8,.0f} ◀") if is_atm else f"  {strike:>8,.0f}  "

        # Call side: OI Chg_OI Vol IV Delta LTP | Strike | LTP Delta IV Vol Chg_OI OI :Put
        call_side = (f"  {_oi_s(c_oi)}  {_chg_s(c_chg_oi)}  {_oi_s(c_vol)}  "
                     f"{_iv_s(c_iv)}  {_dlt_s(c_delta)}  {_ltp_s(c_ltp)}")
        put_side  = (f"  {_ltp_s(p_ltp)}  {_dlt_s(p_delta)}  {_iv_s(p_iv)}  "
                     f"{_oi_s(p_vol)}  {_chg_s(p_chg_oi)}  {_oi_s(p_oi)}")

        line = f"{call_side}  {strike_s}  {put_side}"
        print(bold(line) if is_atm else line)

    print()
    print(f"  {dim('CALL')} ← OI  ChgOI  Vol  IV  Delta  LTP  |  Strike  |  LTP  Delta  IV  Vol  ChgOI  OI → {dim('PUT')}")
    print(f"  {dim(f'Showing ±{n_strikes} strikes around ATM  •  T={T:.4f}y  •  r=6.5%  •  IV computed via Newton-Raphson')}")
    print()


# ── main ──────────────────────────────────────────────────────────────────────

from config.instruments import INDEX_INSTRUMENTS as _IDX  # noqa: E402

SYMBOLS = {
    "nifty 50":      _IDX["NIFTY50"],
    "nifty":         _IDX["NIFTY50"],
    "nifty bank":    _IDX["BANKNIFTY"],
    "banknifty":     _IDX["BANKNIFTY"],
    "bank nifty":    _IDX["BANKNIFTY"],
    "finnifty":      _IDX["FINNIFTY"],
    "midcap nifty":  _IDX["MIDCPNIFTY"],
}


def main():
    parser = argparse.ArgumentParser(description="Option chain viewer")
    parser.add_argument("--symbol",  default="Nifty 50",
                        help="Index/symbol (default: Nifty 50)")
    parser.add_argument("--expiry",  help="Expiry date YYYY-MM-DD (default: next monthly)")
    parser.add_argument("--strikes", type=int, default=10,
                        help="Number of strikes each side of ATM (default: 10)")
    parser.add_argument("--weekly",  action="store_true", help="Use next weekly expiry")
    parser.add_argument("--refresh", type=int, default=0,
                        help="Auto-refresh seconds (0=one-shot)")
    parser.add_argument("--list-expiries", action="store_true",
                        help="List available expiries and exit")
    parser.add_argument("--token",   help="Explicit access token")
    args = parser.parse_args()

    _load_env()
    token = _find_token(args.token)
    if not token:
        print(f"{R}No token found.{RESET}  Run: python scripts/upstox_login.py")
        sys.exit(1)

    symbol_name   = args.symbol
    instrument_key = SYMBOLS.get(symbol_name.lower(), f"NSE_INDEX|{symbol_name}")

    # List expiries
    if args.list_expiries:
        print(f"\n  Fetching expiries for {symbol_name}...")
        expiries = _list_expiries(token, instrument_key)
        if expiries:
            print(f"\n  Available expiries ({len(expiries)}):")
            for e in expiries:
                print(f"    {e}")
        else:
            print("  Could not fetch expiries.")
        return

    # Determine expiry
    if args.expiry:
        expiry = args.expiry
    elif args.weekly:
        expiry = _next_weekly_expiry()
    else:
        expiry = _next_monthly_expiry()

    # Fetch spot
    import requests
    def _get_spot() -> float:
        try:
            r = requests.get(
                f"{BASE}/market-quote/ltp?instrument_key={_enc(instrument_key)}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                resp_key = instrument_key.replace("|", ":")
                return float(data.get(resp_key, {}).get("last_price", 0))
        except Exception:
            pass
        return 0.0

    if args.refresh > 0:
        try:
            while True:
                spot = _get_spot()
                if not spot:
                    print(f"  {yellow('Could not fetch spot price.')}")
                else:
                    _render_chain(token, symbol_name, instrument_key, expiry, args.strikes, spot)
                print(f"  {dim(f'Refreshing in {args.refresh}s  •  Ctrl+C to exit')}")
                time.sleep(args.refresh)
        except KeyboardInterrupt:
            print(f"\n  {dim('Exiting.')}\n")
    else:
        spot = _get_spot()
        if not spot:
            print(f"  {yellow('Could not fetch spot price — chain will show without ATM highlight.')}")
            spot = 0.0
        _render_chain(token, symbol_name, instrument_key, expiry, args.strikes, spot)


if __name__ == "__main__":
    main()
