#!/usr/bin/env python
"""
Live Signal Scanner
===================

Fetches Upstox market data and runs the full MetaStrategyEngine on each symbol.
Shows which trading signals are firing right now, the detected market regime,
stop-loss/take-profit levels, and per-strategy confidence scores.

Bridges: Upstox REST API → FeatureBuilder → MetaStrategyEngine → terminal display

Usage:
    python scripts/live_signals.py
    python scripts/live_signals.py --symbols RELIANCE,TCS,HDFCBANK,INFY
    python scripts/live_signals.py --refresh 120            # re-scan every 2 min
    python scripts/live_signals.py --buy-only
    python scripts/live_signals.py --sell-only
    python scripts/live_signals.py --min-confidence 0.6
    python scripts/live_signals.py --timeframe 1d           # 1d | 1h | 15m
    python scripts/live_signals.py --all-signals            # show every signal, not just best
    python scripts/live_signals.py --no-features            # skip FeatureBuilder (faster)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Colour helpers ────────────────────────────────────────────────────────────

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
C = "\033[96m"; DIM = "\033[2m"; E = "\033[0m"; CLEAR = "\033[2J\033[H"

def green(s):  return f"{G}{s}{E}"
def red(s):    return f"{R}{s}{E}"
def yellow(s): return f"{Y}{s}{E}"
def cyan(s):   return f"{C}{s}{E}"
def bold(s):   return f"{B}{s}{E}"
def dim(s):    return f"{DIM}{s}{E}"


# ── Instrument key registry ───────────────────────────────────────────────────

# symbol → Upstox instrument_key
INSTRUMENTS: dict[str, str] = {
    # Indices
    "NIFTY50":     "NSE_INDEX|Nifty 50",
    "NIFTY":       "NSE_INDEX|Nifty 50",
    "BANKNIFTY":   "NSE_INDEX|Nifty Bank",
    "FINNIFTY":    "NSE_INDEX|Nifty Fin Service",
    "MIDCAP":      "NSE_INDEX|NIFTY MIDCAP 150",
    "VIXINDIA":    "NSE_INDEX|India VIX",
    "NIFTYIT":     "NSE_INDEX|Nifty IT",
    # Large-cap equities (ISIN-keyed)
    "RELIANCE":    "NSE_EQ|INE002A01018",
    "TCS":         "NSE_EQ|INE467B01029",
    "HDFCBANK":    "NSE_EQ|INE040A01034",
    "INFY":        "NSE_EQ|INE009A01021",
    "ICICIBANK":   "NSE_EQ|INE090A01021",
    "SBIN":        "NSE_EQ|INE062A01020",
    "BAJFINANCE":  "NSE_EQ|INE296A01024",
    "BHARTIARTL":  "NSE_EQ|INE397D01024",
    "KOTAKBANK":   "NSE_EQ|INE237A01028",
    "LT":          "NSE_EQ|INE018A01030",
    "AXISBANK":    "NSE_EQ|INE238A01034",
    "WIPRO":       "NSE_EQ|INE075A01022",
    "TATAMOTORS":  "NSE_EQ|INE155A01022",
    "HCLTECH":     "NSE_EQ|INE860A01027",
    "ITC":         "NSE_EQ|INE154A01025",
    "SUNPHARMA":   "NSE_EQ|INE044A01036",
    "ONGC":        "NSE_EQ|INE213A01029",
    "MARUTI":      "NSE_EQ|INE585B01010",
    "NTPC":        "NSE_EQ|INE733E01010",
    "POWERGRID":   "NSE_EQ|INE752E01010",
    "TITAN":       "NSE_EQ|INE280A01028",
    "ULTRACEMCO":  "NSE_EQ|INE481G01011",
    "ADANIPORTS":  "NSE_EQ|INE742F01042",
    "JSWSTEEL":    "NSE_EQ|INE019A01038",
    "TATASTEEL":   "NSE_EQ|INE081A01020",
    "HINDUNILVR":  "NSE_EQ|INE030A01027",
    "NESTLEIND":   "NSE_EQ|INE239A01024",
    "ASIANPAINT":  "NSE_EQ|INE021A01026",
}

# Default watchlist
DEFAULT_SYMBOLS = [
    "NIFTY50", "BANKNIFTY",
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BAJFINANCE", "AXISBANK",
]

# Timeframe → Upstox interval string and lookback days
_TF_CONFIG = {
    "1d":  ("day",       365),
    "1h":  ("60minute",  90),
    "30m": ("30minute",  60),
    "15m": ("15minute",  45),
    "5m":  ("5minute",   30),
}


# ── Token + env loading ───────────────────────────────────────────────────────

def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v


def _get_token(explicit: str = None) -> tuple[str, float]:
    """
    Returns (token, age_hours).
    age_hours = -1 means unknown (env var with no token file).
    Raises SystemExit if token is expired (>23h) or missing.
    """
    tf = ROOT / "data" / "upstox_token.json"

    # Always try the token file first — it carries obtained_at for age tracking
    file_token, file_age = "", -1.0
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            file_age = (time.time() - d.get("obtained_at", 0)) / 3600
            if d.get("access_token"):
                file_token = d["access_token"]
        except Exception:
            pass

    # Explicit --token arg takes priority but we still report age from file
    token = explicit or os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip() or file_token

    if not token:
        print(f"\n{R}No token found.{E}")
        print("Run: python scripts/upstox_login.py")
        sys.exit(1)

    # Age check — only knowable from the token file
    age = file_age if file_token and token == file_token else -1.0

    if age >= 23:
        print(f"\n{R}Token expired{E} (age {age:.1f}h — Upstox tokens last 23h).")
        print("Run: python scripts/upstox_login.py --force")
        print("Or set up auto-renewal: bash scripts/auto_login.sh")
        sys.exit(1)

    if 0 <= age >= 20:
        print(f"{Y}Token is {age:.1f}h old — expires in {23 - age:.1f}h.{E}")
        print(f"  Consider running: bash scripts/auto_login.sh")

    return token, age


# ── Upstox data fetching ──────────────────────────────────────────────────────

def _encode(key: str) -> str:
    return key.replace("|", "%7C").replace(" ", "%20")


def _fetch_ohlcv(token: str, instrument_key: str, interval: str,
                 days: int) -> "pd.DataFrame":
    import requests
    import pandas as pd

    key = _encode(instrument_key)
    to_d = date.today().isoformat()
    from_d = (date.today() - timedelta(days=days)).isoformat()

    url = f"https://api.upstox.com/v2/historical-candle/{key}/{interval}/{to_d}/{from_d}"
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=12,
        )
        if r.status_code == 401:
            raise PermissionError("Token expired — run: python scripts/upstox_login.py --force")
        if r.status_code != 200:
            return pd.DataFrame()
        candles = r.json().get("data", {}).get("candles", [])
    except PermissionError:
        raise
    except Exception:
        return pd.DataFrame()

    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].apply(float)
    return df


def _fetch_ltp(token: str, instrument_keys: list[str]) -> dict[str, float]:
    """Fetch current LTPs for display. Returns {instrument_key: ltp}."""
    import requests
    keys = ",".join(_encode(k) for k in instrument_keys)
    try:
        r = requests.get(
            f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={keys}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=8,
        )
        if r.status_code != 200:
            return {}
        data = r.json().get("data", {})
        return {k.replace(":", "|"): v.get("last_price", 0.0) for k, v in data.items()}
    except Exception:
        return {}


# ── Strategy engine bootstrap ─────────────────────────────────────────────────

_MIN_CFG: dict = {
    "strategies": {"enabled": [], "weights": {}},
    "risk": {"max_risk_per_trade": 0.01, "trailing_stop_pct": 0.02},
    "execution": {"commission": 0.001, "slippage_pct": 0.001},
    "data": {"warmup_bars": 50},
    "system": {"mode": "paper"},
}


def _load_engine():
    """Load MetaStrategyEngine, returning (engine, error_str)."""
    try:
        from strategies.meta_engine import MetaStrategyEngine
        engine = MetaStrategyEngine(_MIN_CFG)
        return engine, None
    except Exception as e:
        return None, str(e)


def _load_feature_builder():
    try:
        from feature_engine.feature_builder import FeatureBuilder
        return FeatureBuilder(), None
    except Exception as e:
        return None, str(e)


# ── Signal scanning ───────────────────────────────────────────────────────────

def _scan_symbol(token: str, symbol: str, instrument_key: str,
                 interval: str, days: int,
                 engine, fb, use_features: bool) -> dict:
    """Return a dict with scan results for one symbol."""
    result = {
        "symbol": symbol,
        "ltp": 0.0,
        "signals": [],
        "best": None,
        "error": None,
        "bars": 0,
    }

    import pandas as pd

    df = _fetch_ohlcv(token, instrument_key, interval, days)
    if df.empty or len(df) < 60:
        result["error"] = f"insufficient data ({len(df)} bars)"
        return result

    result["bars"] = len(df)
    result["ltp"] = float(df["close"].iloc[-1])

    if use_features and fb is not None:
        try:
            df = fb.build(df)
            if df.empty or len(df) < 30:
                result["error"] = "too few bars after feature build"
                return result
        except Exception as e:
            result["error"] = f"feature build failed: {e}"
            return result

    if engine is None:
        result["error"] = "strategy engine unavailable"
        return result

    try:
        signals = engine.generate_signals(symbol, df)
        result["signals"] = signals
        result["best"] = engine.best_signal(signals) if signals else None
    except Exception as e:
        result["error"] = f"signal gen failed: {e}"

    return result


# ── Display ───────────────────────────────────────────────────────────────────

_REGIME_COLORS = {
    "TRENDING_UP":      green,
    "TRENDING_DOWN":    red,
    "RANGING":          yellow,
    "HIGH_VOLATILITY":  lambda s: f"\033[95m{s}{E}",  # magenta
    "LOW_VOLATILITY":   dim,
    "UNKNOWN":          dim,
}


def _regime_str(regime: str) -> str:
    short = regime.replace("_", " ").title()[:12]
    fn = _REGIME_COLORS.get(regime, dim)
    return fn(f"{short:<12}")


def _signal_str(sig) -> str:
    if sig is None:
        return dim(f"{'—':<8}")
    from strategies.base import SignalType
    st = sig.signal_type
    if st == SignalType.BUY:
        return green(f"{'BUY  ↑':<8}")
    elif st == SignalType.SELL:
        return red(f"{'SELL ↓':<8}")
    elif st in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
        return yellow(f"{'CLOSE':<8}")
    return dim(f"{'HOLD':<8}")


def _conf_bar(conf: float) -> str:
    filled = int(conf * 10)
    bar = "█" * filled + "░" * (10 - filled)
    if conf >= 0.75:
        return green(bar)
    elif conf >= 0.5:
        return yellow(bar)
    return red(bar)


def _print_header(args, now_str: str):
    print(CLEAR, end="")
    tf_label = args.timeframe
    sym_count = len(args.resolved_symbols)
    print(bold(f"\n  Live Signal Scanner  •  {now_str}  •  TF:{tf_label}  •  {sym_count} symbols"))
    print("  " + "═" * 110)
    print(f"  {'Symbol':<14}  {'LTP':>12}  {'Regime':<14}  {'Signal':<10}  "
          f"{'Strategy':<24}  {'Conf':>4}  {'Bars':<7}  {'SL':>12}  {'TP':>12}")
    print("  " + "─" * 110)


def _print_row(res: dict, all_signals: bool, min_conf: float,
               buy_only: bool, sell_only: bool):
    sym = res["symbol"]
    ltp = res["ltp"]
    err = res["error"]
    best = res["best"]

    if err:
        print(f"  {sym:<14}  {'—':>12}  {dim('error'):<14}  "
              f"{dim(err[:50])}")
        return

    # Apply filters
    if best is not None:
        from strategies.base import SignalType
        st = best.signal_type
        if buy_only and st != SignalType.BUY:
            return
        if sell_only and st != SignalType.SELL:
            return
        if best.confidence < min_conf:
            return

    # Detect regime from last generated signals (or from first signal metadata)
    regime = "UNKNOWN"
    if res["signals"]:
        regime = res["signals"][0].metadata.get("regime", "UNKNOWN")

    ltp_s = f"₹{ltp:>10,.2f}"

    if best is None:
        print(f"  {sym:<14}  {ltp_s}  {_regime_str(regime)}  {dim('HOLD'+'     ')}  "
              f"{dim('—'*24)}  {dim('  —')}  {res['bars']:<7}")
        return

    sig_rows = [best] if not all_signals else res["signals"]

    for i, sig in enumerate(sig_rows):
        if sig.confidence < min_conf:
            continue
        sym_col = sym if i == 0 else ""
        ltp_col = ltp_s if i == 0 else " " * 13
        reg_col = _regime_str(regime) if i == 0 else " " * 14
        bars_col = str(res["bars"]) if i == 0 else ""

        sl_s = f"₹{sig.stop_loss:>10,.2f}" if sig.stop_loss else dim("—")
        tp_s = f"₹{sig.take_profit:>10,.2f}" if sig.take_profit else dim("—")
        strategy_short = sig.strategy[:22]

        print(f"  {sym_col:<14}  {ltp_col}  {reg_col}  {_signal_str(sig)}  "
              f"{strategy_short:<24}  {_conf_bar(sig.confidence)}  "
              f"{bars_col:<7}  {sl_s}  {tp_s}")


def _print_summary(results: list, elapsed: float):
    signals = [r for r in results if r["best"] is not None and not r["error"]]
    buys    = [r for r in signals
               if hasattr(r["best"], "signal_type")
               and r["best"].signal_type.value == "buy"]
    sells   = [r for r in signals
               if hasattr(r["best"], "signal_type")
               and r["best"].signal_type.value == "sell"]
    errors  = [r for r in results if r["error"]]

    print("  " + "─" * 110)
    print(f"\n  {bold('Summary:')}  "
          f"{green(f'{len(buys)} BUY')}  •  "
          f"{red(f'{len(sells)} SELL')}  •  "
          f"{dim(f'{len(errors)} errors')}  •  "
          f"{dim(f'scan took {elapsed:.1f}s')}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Live Upstox signal scanner")
    parser.add_argument("--symbols",        default="",
                        help="Comma-separated symbols (default: built-in watchlist)")
    parser.add_argument("--refresh",        type=int, default=0,
                        help="Auto-refresh interval in seconds (0=one-shot)")
    parser.add_argument("--timeframe",      default="1d",
                        choices=list(_TF_CONFIG.keys()),
                        help="Candle timeframe (default: 1d)")
    parser.add_argument("--days",           type=int, default=0,
                        help="Lookback days (default: auto per timeframe)")
    parser.add_argument("--buy-only",       action="store_true")
    parser.add_argument("--sell-only",      action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--all-signals",    action="store_true",
                        help="Show all firing signals per symbol (not just best)")
    parser.add_argument("--no-features",    action="store_true",
                        help="Skip FeatureBuilder (faster but fewer indicators)")
    parser.add_argument("--token",          help="Explicit access token")
    args = parser.parse_args()

    _load_env()
    token, token_age = _get_token(args.token)   # exits on expired/missing

    # Resolve symbols
    raw_syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] \
               if args.symbols else DEFAULT_SYMBOLS
    resolved: list[tuple[str, str]] = []
    unknown: list[str] = []
    for sym in raw_syms:
        key = INSTRUMENTS.get(sym)
        if key:
            resolved.append((sym, key))
        else:
            unknown.append(sym)

    if unknown:
        print(f"{Y}Unknown symbols (skipped): {', '.join(unknown)}{E}")
        print(f"  Known: {', '.join(sorted(INSTRUMENTS.keys()))}")

    if not resolved:
        print(f"{R}No valid symbols to scan.{E}")
        sys.exit(1)

    args.resolved_symbols = resolved

    interval, default_days = _TF_CONFIG[args.timeframe]
    days = args.days or default_days

    # Load strategy engine (once)
    print(f"\n{DIM}Loading strategy engine...{E}", end="", flush=True)
    engine, eng_err = _load_engine()
    fb, fb_err = (None, None) if args.no_features else _load_feature_builder()
    use_features = not args.no_features and fb is not None

    if eng_err:
        print(f"\n{Y}Strategy engine error: {eng_err}{E}")
        print("  Signals will not be available. Check your installation.")
    else:
        n = len(engine.strategies)
        print(f"\r{DIM}Strategy engine ready — {n} strategies loaded{E}  ")

    if fb_err and not args.no_features:
        print(f"{Y}FeatureBuilder error: {fb_err} — running without features{E}")

    # ML model existence check
    models_dir = ROOT / "models"
    missing_models = [
        sym for sym, _ in resolved
        if not sym.startswith("NIFTY") and not sym.startswith("BANK")
        and not (models_dir / f"{sym}_ensemble.pkl").exists()
    ]
    if missing_models:
        print(f"\n{Y}No ML models for: {', '.join(missing_models[:6])}"
              f"{'...' if len(missing_models) > 6 else ''}{E}")
        print(f"  MLClassifierStrategy disabled for these symbols.")
        print(f"  Run: python main.py --mode train\n")

    def _run_scan():
        from datetime import datetime
        from utils.timeutils import is_market_session, minutes_to_market_close

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        t0 = time.perf_counter()

        if not is_market_session():
            from utils.timeutils import next_market_open
            nxt = next_market_open()
            print(CLEAR, end="")
            print(bold(f"\n  Live Signal Scanner  •  {now_str}"))
            print(f"  {Y}Market is closed.{E}  Next open: {nxt.strftime('%A %Y-%m-%d %H:%M IST')}")
            print(f"  Historical signals shown (may not reflect current conditions).\n")
        else:
            mins_left = minutes_to_market_close()
            if mins_left <= 30:
                print(f"\n  {Y}Market closes in {mins_left} min.{E}  "
                      f"(MIS squareoff at 3:14 PM IST)\n")

        results = []
        for sym, ikey in resolved:
            res = _scan_symbol(token, sym, ikey, interval, days,
                               engine, fb, use_features)
            results.append(res)

        elapsed = time.perf_counter() - t0
        _print_header(args, now_str)
        for res in results:
            _print_row(res, args.all_signals, args.min_confidence,
                       args.buy_only, args.sell_only)
        _print_summary(results, elapsed)
        print()

    if args.refresh > 0:
        try:
            while True:
                _run_scan()
                from utils.timeutils import is_market_session, minutes_to_market_open
                if not is_market_session():
                    mins = minutes_to_market_open()
                    if mins > args.refresh:
                        # Sleep in chunks, waking to show a countdown
                        sleep_chunk = min(args.refresh, 300)
                        print(f"  {dim(f'Market closed — {mins} min to open.  '
                                       f'Checking again in {sleep_chunk}s  •  Ctrl+C to exit')}")
                        time.sleep(sleep_chunk)
                        continue
                print(f"  {dim(f'Next scan in {args.refresh}s  •  Ctrl+C to exit')}")
                time.sleep(args.refresh)
        except KeyboardInterrupt:
            print(f"\n  {dim('Exiting.')}\n")
    else:
        _run_scan()


if __name__ == "__main__":
    main()
