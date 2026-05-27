#!/usr/bin/env python
"""
Quick Token Status Check
========================

One-liner to check if your current Upstox token is valid and show live prices.
No setup needed — reads token from .env or data/upstox_token.json automatically.

Usage:
    python scripts/check_token.py
    python scripts/check_token.py --token eyJ0eXAi...
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v


def _find_token(explicit=None):
    if explicit:
        return explicit, "argument"
    t = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if t:
        return t, ".env / env-var"
    tf = ROOT / "data" / "upstox_token.json"
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            age = (time.time() - d.get("obtained_at", 0)) / 3600
            if d.get("access_token") and age < 23:
                return d["access_token"], f"token file (age {age:.1f}h)"
        except Exception:
            pass
    return None, None


def main():
    import argparse, requests

    parser = argparse.ArgumentParser()
    parser.add_argument("--token", help="Explicit token to check")
    args = parser.parse_args()

    _load_env()
    token, source = _find_token(args.token)

    G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"; E = "\033[0m"

    print(f"\n{B}Upstox Token Check{E}")
    print("─" * 50)

    if not token:
        print(f"{R}No token found.{E}")
        print("Run: python scripts/upstox_login.py")
        sys.exit(1)

    print(f"Source : {source}")
    print(f"Token  : {token[:40]}...")

    # Hit LTP endpoint
    def _enc(k): return k.replace("|", "%7C").replace(" ", "%20")
    keys = ",".join(_enc(k) for k in [
        "NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank", "NSE_INDEX|India VIX"
    ])
    try:
        r = requests.get(
            f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={keys}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
    except requests.exceptions.Timeout:
        print(f"{R}Request timed out.{E} Upstox API unreachable.")
        sys.exit(1)
    except Exception as e:
        print(f"{R}Request failed: {e}{E}")
        sys.exit(1)

    print(f"Status : HTTP {r.status_code}")

    if r.status_code == 401:
        print(f"\n{R}Token EXPIRED or INVALID.{E}")
        print("Run: python scripts/upstox_login.py --force")
        sys.exit(1)
    elif r.status_code == 403:
        print(f"\n{Y}Token VALID but insufficient scope for this endpoint.{E}")
        print("(Analytics token — market data only, no trading.)")
        sys.exit(0)
    elif r.status_code != 200:
        print(f"\n{Y}Unexpected status {r.status_code}.{E}")
        print(r.text[:200])
        sys.exit(1)

    data = r.json().get("data", {})
    nifty = data.get("NSE_INDEX:Nifty 50", {}).get("last_price")
    bank  = data.get("NSE_INDEX:Nifty Bank", {}).get("last_price")
    vix   = data.get("NSE_INDEX:India VIX", {}).get("last_price")

    print(f"\n{G}Token is VALID.{E}")
    print("─" * 50)
    if nifty: print(f"  Nifty 50    ₹{nifty:>10,.2f}")
    if bank:  print(f"  Bank Nifty  ₹{bank:>10,.2f}")
    if vix:   print(f"  India VIX      {vix:>7.2f}")
    if not any([nifty, bank, vix]):
        print(f"  {Y}No price data (market may be closed){E}")
    print("─" * 50)
    print()


if __name__ == "__main__":
    main()
