#!/usr/bin/env python
"""
Upstox Connection Test
======================

Verifies your Upstox token is working and tests every available API endpoint.
Run this after logging in with `python scripts/upstox_login.py`.

Tested endpoints:
  - Market data: LTP, full quotes, OHLCV depth
  - Historical: daily, weekly, intraday candles
  - Instrument search
  - Options chain
  - India VIX
  - User profile (only for full trading tokens)
  - Portfolio: holdings, positions, funds (only for full trading tokens)

Usage:
    python scripts/test_upstox.py
    python scripts/test_upstox.py --token eyJ0eXAi...   # explicit token
    python scripts/test_upstox.py --verbose              # show raw responses
    python scripts/test_upstox.py --market-only          # skip trading endpoints
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Colour helpers ────────────────────────────────────────────────────────────

def _green(s):  return f"\033[92m{s}\033[0m"
def _red(s):    return f"\033[91m{s}\033[0m"
def _yellow(s): return f"\033[93m{s}\033[0m"
def _bold(s):   return f"\033[1m{s}\033[0m"
def _dim(s):    return f"\033[2m{s}\033[0m"


PASS = _green("PASS")
FAIL = _red("FAIL")
SKIP = _yellow("SKIP")
WARN = _yellow("WARN")


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(token: str, path: str, params: dict = None, verbose: bool = False) -> dict:
    """
    Build URL manually — avoids double-encoding pre-encoded instrument keys.
    instrument_key values contain %7C / %20 which requests would re-encode to %257C.
    """
    import requests
    base = f"https://api.upstox.com/v2{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{base}?{qs}"
    else:
        url = base
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=10,
    )
    if verbose:
        print(f"    {_dim(f'GET {url[:100]}')}")
        print(f"    {_dim(f'Status: {r.status_code}')}")
    return {"status_code": r.status_code, "body": r.json() if r.content else {}}


def _encode(key: str) -> str:
    return key.replace("|", "%7C").replace(" ", "%20")


def _date(days_back: int) -> str:
    return (date.today() - timedelta(days=days_back)).isoformat()


# ── Test runner ───────────────────────────────────────────────────────────────

class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.warnings = 0

    def check(self, label: str, condition: bool, detail: str = "", warn_only: bool = False):
        if condition:
            self.passed += 1
            print(f"  {PASS}  {label}")
            if detail:
                print(f"        {_dim(detail)}")
        elif warn_only:
            self.warnings += 1
            print(f"  {WARN}  {label}")
            if detail:
                print(f"        {_dim(detail)}")
        else:
            self.failed += 1
            print(f"  {FAIL}  {label}")
            if detail:
                print(f"        {_dim(detail)}")

    def skip(self, label: str, reason: str = ""):
        self.skipped += 1
        print(f"  {SKIP}  {label}" + (f"  {_dim(reason)}" if reason else ""))

    def summary(self):
        total = self.passed + self.failed + self.skipped
        print()
        print("─" * 60)
        print(f"  Results: {self.passed} passed, {self.failed} failed, "
              f"{self.skipped} skipped, {self.warnings} warnings  "
              f"(total: {total})")
        if self.failed == 0:
            print(f"  {_green('All checks passed.')}")
        else:
            print(f"  {_red(f'{self.failed} check(s) failed.')}")
        print("─" * 60)
        return self.failed == 0


# ── Token loading ─────────────────────────────────────────────────────────────

def load_token(explicit: str = None) -> str:
    if explicit:
        return explicit

    # 1. env var
    t = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if t:
        return t

    # 2. .env file
    env_path = ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("UPSTOX_ACCESS_TOKEN="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val

    # 3. token file (from previous login)
    token_file = ROOT / "data" / "upstox_token.json"
    if token_file.exists():
        try:
            with open(token_file) as f:
                data = json.load(f)
            age_h = (time.time() - data.get("obtained_at", 0)) / 3600
            t = data.get("access_token", "")
            if t and age_h < 23:
                return t
        except Exception:
            pass

    return ""


# ── Test suites ───────────────────────────────────────────────────────────────

def test_connectivity(token: str, r: Results, verbose: bool):
    print(_bold("\n[1] Connectivity & Token Validity"))

    resp = _get(token, "/market-quote/ltp",
                {"instrument_key": _encode("NSE_INDEX|Nifty 50")}, verbose)

    r.check("API reachable (HTTP 200)", resp["status_code"] == 200,
            detail=f"Status: {resp['status_code']}")

    data = resp["body"].get("data", {})
    nifty = data.get("NSE_INDEX:Nifty 50", {})
    ltp = nifty.get("last_price")

    r.check("Token accepted (not 401/403)",
            resp["status_code"] not in (401, 403),
            detail="401/403 = token expired or invalid scope")
    r.check("Response contains LTP data", ltp is not None,
            detail=f"Nifty 50 LTP: ₹{ltp}" if ltp else "no data (market may be closed)")


def test_ltp(token: str, r: Results, verbose: bool):
    print(_bold("\n[2] LTP — Live Last Traded Price"))

    instruments = {
        "Nifty 50":     "NSE_INDEX|Nifty 50",
        "Bank Nifty":   "NSE_INDEX|Nifty Bank",
        "Nifty IT":     "NSE_INDEX|Nifty IT",
        "Nifty Midcap": "NSE_INDEX|NIFTY MIDCAP 150",
        "India VIX":    "NSE_INDEX|India VIX",
        "RELIANCE":     "NSE_EQ|INE002A01018",
        "TCS":          "NSE_EQ|INE467B01029",
        "HDFCBANK":     "NSE_EQ|INE040A01034",
    }

    keys = ",".join(_encode(k) for k in instruments.values())
    resp = _get(token, "/market-quote/ltp", {"instrument_key": keys}, verbose)

    r.check("Bulk LTP request succeeded", resp["status_code"] == 200,
            detail=f"Fetched {len(instruments)} instruments at once")

    data = resp["body"].get("data", {})
    prices = {}
    for name, key in instruments.items():
        # key format in response replaces | with :
        resp_key = key.replace("|", ":")
        entry = data.get(resp_key, {})
        ltp = entry.get("last_price")
        prices[name] = ltp
        if ltp is not None:
            r.check(f"  {name}: ₹{ltp:,.2f}", ltp > 0)
        else:
            r.skip(f"  {name}", "no data (instrument not trading or market closed)")


def test_full_quotes(token: str, r: Results, verbose: bool):
    print(_bold("\n[3] Full OHLCV Quotes"))

    resp = _get(token, "/market-quote/quotes",
                {"instrument_key": _encode("NSE_INDEX|Nifty 50")}, verbose)
    r.check("Full quote endpoint returns 200", resp["status_code"] == 200)

    data = resp["body"].get("data", {}).get("NSE_INDEX:Nifty 50", {})
    ohlc = data.get("ohlc", {})
    if ohlc:
        r.check("OHLC data present", all(k in ohlc for k in ("open", "high", "low", "close")),
                detail=f"O:{ohlc.get('open')} H:{ohlc.get('high')} L:{ohlc.get('low')} C:{ohlc.get('close')}")
        if ohlc.get("high") and ohlc.get("low"):
            r.check("High >= Low", float(ohlc["high"]) >= float(ohlc["low"]),
                    detail=f"H:{ohlc['high']} >= L:{ohlc['low']}")
    else:
        r.skip("OHLC data", "market closed or no data")

    depth = data.get("depth", {})
    r.check("Order depth present", bool(depth), warn_only=True)


def test_historical(token: str, r: Results, verbose: bool):
    print(_bold("\n[4] Historical Candles"))

    key = _encode("NSE_INDEX|Nifty 50")
    to_d = date.today().isoformat()

    # Daily
    from_d = _date(60)
    resp = _get(token, f"/historical-candle/{key}/day/{to_d}/{from_d}", verbose=verbose)
    candles = resp["body"].get("data", {}).get("candles", [])
    r.check(f"Daily candles (60 days): {len(candles)} bars", len(candles) > 0)
    if candles:
        last = candles[-1]
        r.check("Candle format: [ts, O, H, L, C, V, OI]", len(last) >= 6,
                detail=f"Last: {last[:6]}")

    # Weekly
    from_w = _date(180)
    resp_w = _get(token, f"/historical-candle/{key}/week/{to_d}/{from_w}", verbose=verbose)
    weekly = resp_w["body"].get("data", {}).get("candles", [])
    r.check(f"Weekly candles (6 months): {len(weekly)} bars", len(weekly) > 0)

    # Monthly
    from_m = _date(730)
    resp_m = _get(token, f"/historical-candle/{key}/month/{to_d}/{from_m}", verbose=verbose)
    monthly = resp_m["body"].get("data", {}).get("candles", [])
    r.check(f"Monthly candles (2 years): {len(monthly)} bars", len(monthly) > 0)


def test_intraday(token: str, r: Results, verbose: bool):
    print(_bold("\n[5] Intraday Candles"))

    key = _encode("NSE_INDEX|Nifty 50")

    for interval in ("1minute", "30minute"):
        resp = _get(token, f"/historical-candle/intraday/{key}/{interval}", verbose=verbose)
        candles = resp["body"].get("data", {}).get("candles", [])
        r.check(f"{interval}: {len(candles)} bars",
                resp["status_code"] == 200,
                detail="0 bars = market closed today (expected outside 09:15–15:30 IST)")

        if candles:
            # Verify volume field
            has_vol = len(candles[0]) >= 6 and candles[0][5] is not None
            r.check(f"  {interval} has volume data", has_vol)


def test_instruments(token: str, r: Results, verbose: bool):
    print(_bold("\n[6] Instrument Search"))

    for symbol in ("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"):
        resp = _get(token, f"/instruments/search?query={symbol}&segment=NSE_EQ",
                    verbose=verbose)
        raw = resp["body"].get("data", [])
        items = (raw.get("items", []) if isinstance(raw, dict) else raw) or []
        found = len(items) > 0
        isin = items[0].get("isin", "") if found else ""
        r.check(f"Search '{symbol}': {'found' if found else 'not found'}",
                found, detail=f"ISIN: {isin}" if isin else "no results")


def test_options(token: str, r: Results, verbose: bool):
    print(_bold("\n[7] Options Data"))

    # Try option chain for next monthly expiry
    expiry = (date.today().replace(day=28) + timedelta(days=4)).replace(day=26)
    expiry_str = expiry.isoformat()

    resp = _get(token, "/option/chain",
                {"instrument_key": "NSE_INDEX|Nifty 50", "expiry_date": expiry_str}, verbose)
    code = resp["status_code"]
    r.check(f"Option chain endpoint accessible (status {code})",
            code in (200, 400, 404),
            detail="200=data, 400=bad expiry format, 404=no expiry — all acceptable")

    if code == 200:
        chain_data = resp["body"].get("data", {})
        # data may be a list or dict depending on API version
        has_data = bool(chain_data) and (
            (isinstance(chain_data, list) and len(chain_data) > 0) or
            (isinstance(chain_data, dict) and any(chain_data.values()))
        )
        r.check("Option chain has data", has_data,
                detail=f"type={type(chain_data).__name__} len={len(chain_data) if chain_data else 0}",
                warn_only=True)

    # Greeks computation (uses live spot + Black-Scholes)
    try:
        ltp_resp = _get(token, "/market-quote/ltp",
                        {"instrument_key": _encode("NSE_INDEX|Nifty 50")}, verbose)
        spot = ltp_resp["body"].get("data", {}).get("NSE_INDEX:Nifty 50", {}).get("last_price")

        if spot:
            from feature_engine.greeks import Greeks
            atm = round(spot / 50) * 50
            g = Greeks(S=float(spot), K=float(atm), T=30, r=0.065, sigma=0.15, opt="call")
            r.check(
                f"Black-Scholes Greeks (spot=₹{spot:.0f} ATM={atm})",
                0 < g.delta <= 1.0 and g.gamma > 0 and g.theta < 0 and g.vega > 0,
                detail=f"delta={g.delta:.3f} gamma={g.gamma:.6f} theta={g.theta:.3f} vega={g.vega:.3f}",
            )
        else:
            r.skip("Greeks computation", "no live spot price")
    except ImportError:
        r.skip("Greeks computation", "feature_engine not importable")


def test_user_profile(token: str, r: Results, verbose: bool):
    print(_bold("\n[8] User Profile & Account"))

    resp = _get(token, "/user/profile", verbose=verbose)
    code = resp["status_code"]

    if code == 200:
        profile = resp["body"].get("data", {})
        r.check("Profile endpoint accessible", True,
                detail=f"User: {profile.get('user_name')} | ID: {profile.get('user_id')} | Email: {profile.get('email')}")
    elif code in (401, 403):
        r.skip("User profile", "Analytics token (read-only) — no profile scope")
    else:
        r.check("Profile endpoint accessible", False, detail=f"HTTP {code}")


def test_portfolio(token: str, r: Results, verbose: bool, skip_trading: bool):
    print(_bold("\n[9] Portfolio (Holdings & Positions)"))

    if skip_trading:
        r.skip("Holdings", "skipped (--market-only)")
        r.skip("Positions", "skipped (--market-only)")
        r.skip("Funds/Margins", "skipped (--market-only)")
        return

    for path, label in (
        ("/portfolio/long-term-holdings", "Holdings"),
        ("/portfolio/short-term-positions", "Positions"),
        ("/user/get-funds-and-margin", "Funds & Margins"),
    ):
        resp = _get(token, path, verbose=verbose)
        code = resp["status_code"]
        if code == 200:
            data = resp["body"].get("data", [])
            count = len(data) if isinstance(data, list) else 1
            r.check(f"{label}: {count} item(s)", True)
        elif code in (401, 403):
            r.skip(label, "Analytics/read-only token — no portfolio scope")
        else:
            r.check(f"{label} accessible", False, detail=f"HTTP {code}")


def test_production_modules(token: str, r: Results, verbose: bool):
    print(_bold("\n[10] Production Module Integration"))

    # Fetch live Nifty data first
    try:
        resp = _get(token, "/historical-candle/" + _encode("NSE_INDEX|Nifty 50") +
                    f"/day/{date.today().isoformat()}/{_date(90)}", verbose=verbose)
        candles = resp["body"].get("data", {}).get("candles", [])
    except Exception as e:
        r.skip("All module tests", f"Could not fetch live data: {e}")
        return

    if len(candles) < 30:
        r.skip("All module tests", f"Only {len(candles)} candles (need 30+)")
        return

    import numpy as np
    import pandas as pd

    candles.sort(key=lambda x: x[0])
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts")
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c])

    # FeatureBuilder
    try:
        from feature_engine.feature_builder import FeatureBuilder
        fb = FeatureBuilder()
        df_feat = fb.build(df)
        r.check("FeatureBuilder: built features from live Nifty data",
                len(df_feat.columns) > 10,
                detail=f"{len(df_feat.columns)} feature columns, {len(df_feat)} rows")
    except Exception as e:
        r.check("FeatureBuilder", False, detail=str(e))

    # CVaR
    try:
        from risk_manager.cvar import CVaRRiskManager
        returns_pnl = (df["close"].pct_change().dropna() * 500000).tolist()
        cvar_rm = CVaRRiskManager(capital=500000)
        for pnl in returns_pnl:
            cvar_rm.record_pnl(pnl)
        result = cvar_rm.portfolio_cvar()
        r.check("CVaR on live returns",
                result is not None,
                detail=f"VaR={result.var:.2f}  CVaR={result.cvar:.2f}  method={result.method}" if result else "need 20+ samples")
    except Exception as e:
        r.check("CVaR computation", False, detail=str(e))

    # Monte Carlo
    try:
        from backtester.monte_carlo import run_monte_carlo
        returns_list = df["close"].pct_change().dropna().tolist()
        mc = run_monte_carlo(returns_list, n_simulations=200, method="bootstrap")
        r.check("Monte Carlo (200 sims on live returns)",
                mc.n_simulations == 200,
                detail=f"Sharpe={mc.sharpe_mean:.2f}  p-value={mc.p_value_sharpe:.4f}")
    except Exception as e:
        r.check("Monte Carlo", False, detail=str(e))

    # Kalman hedge ratio
    try:
        from utils.kalman import KalmanHedgeRatio
        # Use first and last 30 days of Nifty as a proxy for "pair"
        prices = df["close"].values
        kf = KalmanHedgeRatio()
        for i in range(min(50, len(prices) // 2)):
            kf.update(prices[i], prices[-(i + 1)])
        uncertainty = float(kf.P[0, 0])
        r.check("Kalman hedge ratio",
                kf.beta != 0,
                detail=f"beta={kf.beta:.4f}  uncertainty(P[0,0])={uncertainty:.4f}")
    except Exception as e:
        r.check("Kalman hedge ratio", False, detail=str(e))

    # Circuit detector
    try:
        from data_engine.circuit_detector import CircuitBreakerDetector
        det = CircuitBreakerDetector()
        prev_close = float(df["close"].iloc[-2])
        curr_price  = float(df["close"].iloc[-1])
        status = det.check_stock("NIFTY50", curr_price, prev_close)
        pct_gap = (curr_price - prev_close) / prev_close * 100
        r.check("Circuit detector on live prices",
                status is not None,
                detail=f"pct_move={pct_gap:.2f}%  circuited={status.is_circuited}  near={status.is_near_circuit}")
    except Exception as e:
        r.check("Circuit detector", False, detail=str(e))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Test Upstox connection")
    parser.add_argument("--token", help="Access token (default: reads from .env / token file)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show HTTP requests")
    parser.add_argument("--market-only", action="store_true", help="Skip trading/portfolio endpoints")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    args = parser.parse_args()

    # Load .env
    env_path = ROOT / args.env
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v

    token = load_token(args.token)

    print("\n" + "=" * 60)
    print("  Upstox Connection Test")
    print("=" * 60)

    if not token:
        print(f"\n  {_red('[ERROR]')} No token found.")
        print("  Options:")
        print("    1. Run: python scripts/upstox_login.py")
        print("    2. Set env var: export UPSTOX_ACCESS_TOKEN=<token>")
        print("    3. Add UPSTOX_ACCESS_TOKEN=<token> to .env")
        sys.exit(1)

    print(f"\n  Token: {token[:40]}...")

    r = Results()

    test_connectivity(token, r, args.verbose)
    test_ltp(token, r, args.verbose)
    test_full_quotes(token, r, args.verbose)
    test_historical(token, r, args.verbose)
    test_intraday(token, r, args.verbose)
    test_instruments(token, r, args.verbose)
    test_options(token, r, args.verbose)
    test_user_profile(token, r, args.verbose)
    test_portfolio(token, r, args.verbose, skip_trading=args.market_only)
    test_production_modules(token, r, args.verbose)

    success = r.summary()

    print()
    if success:
        print("  Ready to run the bot:")
        print("    python main.py --mode paper")
    else:
        print("  Fix the failures above, then try:")
        print("    python scripts/upstox_login.py --force")

    print()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
