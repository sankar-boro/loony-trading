#!/usr/bin/env python
"""
Quick Token Status Check
========================

Checks token validity, decodes JWT expiry, and shows live prices.
Supports production, analytics, extended, and sandbox tokens.

Usage:
    python scripts/check_token.py
    python scripts/check_token.py --token eyJ0eXAi...
    python scripts/check_token.py --sandbox
    python scripts/check_token.py --extended
    python scripts/check_token.py --all         # check all saved tokens
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.instruments import INSTRUMENTS  # noqa: E402

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"; DIM = "\033[2m"; E = "\033[0m"


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


def _decode_jwt(token: str) -> dict:
    """Decode JWT payload without signature verification. Returns {} on failure."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
    except Exception:
        return {}


def _jwt_info(token: str) -> str:
    """Return a human-readable JWT expiry summary line."""
    payload = _decode_jwt(token)
    if not payload:
        return ""
    parts = []
    sub = payload.get("sub", "")
    if sub:
        parts.append(f"sub={sub}")
    exp = payload.get("exp")
    if exp:
        exp_dt = datetime.fromtimestamp(exp)
        remaining = (exp_dt - datetime.now()).total_seconds() / 3600
        color = G if remaining > 2 else (Y if remaining > 0 else R)
        parts.append(f"exp={exp_dt.strftime('%Y-%m-%d %H:%M')}  {color}({remaining:.1f}h remaining){E}")
    iat = payload.get("iat")
    if iat:
        issued = datetime.fromtimestamp(iat)
        parts.append(f"issued={issued.strftime('%Y-%m-%d %H:%M')}")
    return "  ".join(parts)


def _find_token(explicit=None) -> tuple[str, str]:
    if explicit:
        return explicit, "argument"
    t = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if t:
        return t, ".env / env-var"
    tf = ROOT / "data" / "upstox_token.json"
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            from data_engine.upstox.auth import token_hours_left
            age = (time.time() - d.get("obtained_at", 0)) / 3600
            if d.get("access_token") and token_hours_left(d.get("obtained_at", 0)) > 0:
                return d["access_token"], f"token file (age {age:.1f}h)"
        except Exception:
            pass
    return "", ""


def _find_sandbox_token() -> tuple[str, str]:
    t = os.environ.get("UPSTOX_SANDBOX_TOKEN", "").strip()
    if t:
        return t, ".env / env-var (sandbox)"
    tf = ROOT / "data" / "upstox_sandbox_token.json"
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            age = (time.time() - d.get("obtained_at", 0)) / 3600
            if d.get("access_token") and age < 720:
                return d["access_token"], f"sandbox token file (age {age:.1f}h)"
        except Exception:
            pass
    return "", ""


def _find_extended_token() -> tuple[str, str]:
    t = os.environ.get("UPSTOX_EXTENDED_TOKEN", "").strip()
    if t:
        return t, ".env / env-var (extended)"
    tf = ROOT / "data" / "upstox_extended_token.json"
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            age = (time.time() - d.get("obtained_at", 0)) / 3600
            if d.get("access_token") and age < 8760:
                return d["access_token"], f"extended token file (age {age:.0f}h / {age/24:.1f}d)"
        except Exception:
            pass
    return "", ""


def _check_production(token: str, source: str) -> bool:
    """Check a production/extended token via LTP endpoint. Returns True if valid."""
    import requests

    def _enc(k): return k.replace("|", "%7C").replace(" ", "%20")
    from config.instruments import INDEX_INSTRUMENTS as IDX
    keys = ",".join(_enc(IDX[s]) for s in ("NIFTY50", "BANKNIFTY", "VIXINDIA"))
    try:
        r = requests.get(
            f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={keys}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
    except requests.exceptions.Timeout:
        print(f"  Status : {R}Request timed out{E}")
        return False
    except Exception as e:
        print(f"  Status : {R}Request failed: {e}{E}")
        return False

    print(f"  Status : HTTP {r.status_code}")

    if r.status_code == 401:
        print(f"  {R}EXPIRED or INVALID{E}")
        print("  → Run: python scripts/upstox_login.py --force")
        return False
    elif r.status_code == 403:
        print(f"  {Y}VALID — insufficient scope (analytics/read-only token){E}")
        return True
    elif r.status_code != 200:
        print(f"  {Y}Unexpected status {r.status_code}{E}")
        print(f"  {DIM}{r.text[:200]}{E}")
        return False

    data = r.json().get("data", {})
    nifty = data.get("NSE_INDEX:Nifty 50", {}).get("last_price")
    bank  = data.get("NSE_INDEX:Nifty Bank", {}).get("last_price")
    vix   = data.get("NSE_INDEX:India VIX", {}).get("last_price")

    print(f"  {G}VALID{E}")
    if nifty: print(f"    Nifty 50    ₹{nifty:>10,.2f}")
    if bank:  print(f"    Bank Nifty  ₹{bank:>10,.2f}")
    if vix:   print(f"    India VIX      {vix:>7.2f}")
    if not any([nifty, bank, vix]):
        print(f"    {Y}No price data — market may be closed{E}")
    return True


def _check_sandbox(token: str, source: str) -> bool:
    """
    Verify sandbox token by placing a minimal LIMIT order and cancelling it.
    Sandbox only supports order endpoints — no market data.
    """
    import requests

    base = "https://api-sandbox.upstox.com/v2"
    hdrs = {"Authorization": f"Bearer {token}", "Accept": "application/json",
            "Content-Type": "application/json"}

    order_body = {
        "quantity": 1,
        "product": "D",
        "validity": "DAY",
        "price": 1.0,
        "tag": "token_check",
        "instrument_token": INSTRUMENTS["RELIANCE"],
        "order_type": "LIMIT",
        "transaction_type": "BUY",
        "disclosed_quantity": 0,
        "trigger_price": 0,
        "is_amo": False,
    }

    try:
        r = requests.post(f"{base}/order/place", headers=hdrs,
                          json=order_body, timeout=10)
    except Exception as e:
        print(f"  Status : {R}Request failed: {e}{E}")
        return False

    print(f"  Place order: HTTP {r.status_code}")

    if r.status_code == 401:
        print(f"  {R}EXPIRED or INVALID{E}")
        print("  → Generate a new token at: https://upstox.com/developer/apps")
        return False
    elif r.status_code not in (200, 201):
        print(f"  {Y}Unexpected status {r.status_code}{E}")
        try:
            body = r.json()
            print(f"  {DIM}{json.dumps(body)[:200]}{E}")
        except Exception:
            print(f"  {DIM}{r.text[:200]}{E}")
        return False

    order_id = r.json().get("data", {}).get("order_id", "")
    print(f"  {G}VALID{E}  (sandbox order placed: {order_id})")

    # Cancel the test order
    if order_id:
        try:
            cr = requests.delete(
                f"{base}/order/cancel?order_id={order_id}",
                headers=hdrs, timeout=8
            )
            if cr.status_code in (200, 201):
                print(f"  Cleanup: test order cancelled ✓")
            else:
                print(f"  {Y}Could not cancel test order {order_id} (HTTP {cr.status_code}){E}")
        except Exception:
            pass

    return True


def _print_section(title: str):
    print(f"\n{B}{title}{E}")
    print("─" * 56)


def _print_token_header(token: str, source: str):
    print(f"  Source : {source}")
    print(f"  Token  : {token[:40]}...")
    jwt = _jwt_info(token)
    if jwt:
        print(f"  JWT    : {jwt}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Upstox token status checker")
    parser.add_argument("--token",    help="Explicit token to check")
    parser.add_argument("--sandbox",  action="store_true", help="Check sandbox token")
    parser.add_argument("--extended", action="store_true", help="Check extended (1-year) token")
    parser.add_argument("--all",      action="store_true", help="Check all saved tokens")
    args = parser.parse_args()

    _load_env()

    print(f"\n{B}Upstox Token Check{E}")
    print("═" * 56)

    if args.all:
        # Check every token we know about
        tokens_to_check = []

        prod_tok, prod_src = _find_token(args.token)
        if prod_tok:
            tokens_to_check.append(("Production Token", prod_tok, prod_src, "prod"))

        ext_tok, ext_src = _find_extended_token()
        if ext_tok:
            tokens_to_check.append(("Extended Token (1-year)", ext_tok, ext_src, "prod"))

        sb_tok, sb_src = _find_sandbox_token()
        if sb_tok:
            tokens_to_check.append(("Sandbox Token", sb_tok, sb_src, "sandbox"))

        if not tokens_to_check:
            print(f"\n{R}No tokens found.{E}")
            print("Run: python scripts/upstox_login.py")
            sys.exit(1)

        any_valid = False
        for title, tok, src, kind in tokens_to_check:
            _print_section(title)
            _print_token_header(tok, src)
            if kind == "sandbox":
                valid = _check_sandbox(tok, src)
            else:
                valid = _check_production(tok, src)
            if valid:
                any_valid = True

        print()
        sys.exit(0 if any_valid else 1)

    elif args.sandbox:
        _print_section("Sandbox Token")
        token, source = _find_sandbox_token()
        if not token:
            print(f"\n{R}No sandbox token found.{E}")
            print("Run: python scripts/upstox_login.py --sandbox")
            sys.exit(1)
        _print_token_header(token, source)
        ok = _check_sandbox(token, source)
        print()
        sys.exit(0 if ok else 1)

    elif args.extended:
        _print_section("Extended Token (1-year)")
        token, source = _find_extended_token()
        if not token:
            print(f"\n{R}No extended token found.{E}")
            print("Extended tokens are saved automatically during OAuth login.")
            print("Run: python scripts/upstox_login.py --force")
            sys.exit(1)
        _print_token_header(token, source)
        ok = _check_production(token, source)
        print()
        sys.exit(0 if ok else 1)

    else:
        _print_section("Production Token")
        token, source = _find_token(args.token)
        if not token:
            print(f"\n{R}No token found.{E}")
            print("Run: python scripts/upstox_login.py")
            sys.exit(1)
        _print_token_header(token, source)
        ok = _check_production(token, source)
        print()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
