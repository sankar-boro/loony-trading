#!/usr/bin/env python
"""
Strategy Weight Tuner
=====================

Backtests each strategy individually on a set of NSE symbols, computes
Sharpe-normalised weights, and writes the result to config/settings.yaml.

The weight formula is:
    w_i = max(sharpe_i, 0) / sum(max(sharpe_j, 0) for all j)
    then rescaled so the median weight = 1.0

Strategies with Sharpe < 0 receive weight = 0 (disabled).

Usage:
    python scripts/tune_weights.py                        # default symbols, 1-year
    python scripts/tune_weights.py --symbols RELIANCE,TCS
    python scripts/tune_weights.py --days 180             # 6-month window
    python scripts/tune_weights.py --dry-run              # print weights, don't write
    python scripts/tune_weights.py --min-sharpe 0.3       # minimum Sharpe to include
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
DIM = "\033[2m"; C = "\033[96m"; E = "\033[0m"

def green(s):  return f"{G}{s}{E}"
def red(s):    return f"{R}{s}{E}"
def cyan(s):   return f"{C}{s}{E}"
def bold(s):   return f"{B}{s}{E}"
def dim(s):    return f"{DIM}{s}{E}"
def yellow(s): return f"{Y}{s}{E}"


INSTRUMENTS = {
    "RELIANCE":   "NSE_EQ|INE002A01018",
    "TCS":        "NSE_EQ|INE467B01029",
    "HDFCBANK":   "NSE_EQ|INE040A01034",
    "INFY":       "NSE_EQ|INE009A01021",
    "ICICIBANK":  "NSE_EQ|INE090A01021",
    "SBIN":       "NSE_EQ|INE062A01020",
    "AXISBANK":   "NSE_EQ|INE238A01034",
    "NIFTY50":    "NSE_INDEX|Nifty 50",
}

DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]
SETTINGS_FILE   = ROOT / "config" / "settings.yaml"


# ── Data loading ──────────────────────────────────────────────────────────────

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


def _fetch_ohlcv(token: str, instrument_key: str, days: int):
    import requests, pandas as pd
    key = instrument_key.replace("|", "%7C").replace(" ", "%20")
    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=days)).isoformat()
    url = f"https://api.upstox.com/v2/historical-candle/{key}/day/{to_d}/{from_d}"
    try:
        r = requests.get(url,
                         headers={"Authorization": f"Bearer {token}",
                                  "Accept": "application/json"},
                         timeout=12)
        if r.status_code != 200:
            return pd.DataFrame()
        candles = r.json().get("data", {}).get("candles", [])
    except Exception as exc:
        print(f"  {yellow(f'HTTP error: {exc}')}")
        return pd.DataFrame()
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].apply(float)
    return df


# ── Backtest one strategy ─────────────────────────────────────────────────────

def _backtest_strategy(strategy_cls, cfg: dict, data_map: dict[str, any]) -> float:
    """Return median Sharpe across all symbols for one strategy class."""
    import statistics
    from backtester.backtester import Backtester

    sharpes = []
    bt = Backtester(cfg, initial_capital=500_000, product="CNC")
    for sym, df in data_map.items():
        if df.empty or len(df) < 60:
            continue
        try:
            strat = strategy_cls(cfg)
            result = bt.run(df, sym, strategy=strat)
            sh = result.metrics.get("sharpe", 0.0)
            if result.metrics.get("n_trades", 0) >= 3:   # ignore near-zero-trade results
                sharpes.append(sh)
        except Exception as exc:
            print(f"    {dim(f'{strategy_cls.__name__} on {sym}: {exc}')}")
    return statistics.median(sharpes) if sharpes else 0.0


# ── Weight normalisation ──────────────────────────────────────────────────────

def _normalise_weights(sharpe_map: dict[str, float],
                       min_sharpe: float) -> dict[str, float]:
    """
    Sharpe-normalised weights scaled so median weight = 1.0.
    Strategies below min_sharpe get weight 0 (will be excluded from enabled list).
    """
    import statistics
    positive = {n: max(s, 0.0) for n, s in sharpe_map.items() if s >= min_sharpe}
    total = sum(positive.values())
    if total == 0:
        return {n: 1.0 for n in sharpe_map}   # all bad → equal weights

    raw = {n: v / total * len(positive) for n, v in positive.items()}

    # Add zero-weight entries for excluded strategies
    for name in sharpe_map:
        if name not in raw:
            raw[name] = 0.0

    # Rescale so median of positive weights = 1.0
    pos_vals = [v for v in raw.values() if v > 0]
    if pos_vals:
        median = statistics.median(pos_vals)
        if median > 0:
            raw = {n: round(v / median, 3) for n, v in raw.items()}

    return raw


# ── YAML writer ───────────────────────────────────────────────────────────────

def _update_yaml_weights(weights: dict[str, float],
                         enabled: list[str]) -> None:
    """
    Edit config/settings.yaml in-place — update ONLY the strategies.enabled
    and strategies.weights blocks.  Tracks whether we are inside the
    'strategies:' top-level key so we never touch telegram/email/rl enabled flags.
    """
    text = SETTINGS_FILE.read_text()
    lines = text.splitlines()
    out: list[str] = []
    in_strategies = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        # Track top-level section changes
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            in_strategies = line.startswith("strategies:")

        # Replace strategies.enabled — only when inside strategies block
        if in_strategies and line == "  enabled:":
            out.append("  enabled:")
            for name in enabled:
                out.append(f"    - {name}")
            i += 1
            while i < len(lines) and (lines[i].startswith("    -") or
                                       (lines[i].startswith("    #"))):
                i += 1
            continue

        # Replace strategies.weights — only when inside strategies block
        if in_strategies and line == "  weights:":
            out.append("  weights:")
            for name, w in sorted(weights.items()):
                if w > 0:
                    out.append(f"    {name}: {w}")
            i += 1
            while i < len(lines) and lines[i].startswith("    ") and ": " in lines[i]:
                i += 1
            continue

        out.append(line)
        i += 1

    SETTINGS_FILE.write_text("\n".join(out) + "\n")


# ── Strategy registry ─────────────────────────────────────────────────────────

def _get_strategy_classes() -> dict[str, type]:
    from strategies.trend import (
        EmaCrossoverStrategy, MultiTimeframeTrendStrategy,
        SupertrendStrategy, DonchianBreakoutStrategy,
    )
    from strategies.mean_reversion import (
        RsiReversionStrategy, BollingerReversionStrategy,
        ZscoreReversionStrategy, VwapReversionStrategy,
    )
    from strategies.breakout import (
        SupportResistanceBreakoutStrategy, AtrBreakoutStrategy, RangeBreakoutStrategy,
    )
    from strategies.momentum import MacdMomentumStrategy, RsiMomentumStrategy, VolumeMomentumStrategy
    from strategies.candlestick import CandlestickPatternStrategy

    return {
        "ema_crossover":        EmaCrossoverStrategy,
        "multi_tf_trend":       MultiTimeframeTrendStrategy,
        "supertrend":           SupertrendStrategy,
        "donchian_breakout":    DonchianBreakoutStrategy,
        "rsi_mean_reversion":   RsiReversionStrategy,
        "bollinger_reversion":  BollingerReversionStrategy,
        "zscore_reversion":     ZscoreReversionStrategy,
        "vwap_reversion":       VwapReversionStrategy,
        "sr_breakout":          SupportResistanceBreakoutStrategy,
        "breakout_atr":         AtrBreakoutStrategy,
        "range_breakout":       RangeBreakoutStrategy,
        "macd_momentum":        MacdMomentumStrategy,
        "rsi_momentum":         RsiMomentumStrategy,
        "volume_momentum":      VolumeMomentumStrategy,
        "candlestick_pattern":  CandlestickPatternStrategy,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest and tune strategy weights")
    parser.add_argument("--symbols",     default="",
                        help="Comma-separated symbols (default: RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK)")
    parser.add_argument("--days",        type=int, default=365,
                        help="Lookback window in calendar days (default: 365)")
    parser.add_argument("--min-sharpe",  type=float, default=0.0,
                        help="Minimum Sharpe to include in enabled list (default: 0.0)")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Print proposed weights without writing to settings.yaml")
    parser.add_argument("--token",       help="Upstox access token (optional, falls back to file/env)")
    args = parser.parse_args()

    _load_env()

    # Load token
    token_file = ROOT / "data" / "upstox_token.json"
    token = args.token or os.environ.get("UPSTOX_ACCESS_TOKEN", "")
    if not token and token_file.exists():
        try:
            d = json.loads(token_file.read_text())
            token = d.get("access_token", "")
        except Exception:
            pass
    if not token:
        print(f"{R}No Upstox token found.{E} Run: python scripts/upstox_login.py")
        sys.exit(1)

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or DEFAULT_SYMBOLS

    cfg = {
        "strategies": {"enabled": [], "weights": {}},
        "risk": {"max_risk_per_trade": 0.01, "trailing_stop_pct": 0.02},
        "execution": {"commission_intraday": 0.00055, "commission_delivery": 0.0021,
                      "slippage_pct": 0.0005},
        "data": {"warmup_bars": 50},
        "system": {"mode": "backtest"},
    }

    # Pre-load OHLCV data
    print(bold(f"\n  Tuning strategy weights — {len(syms)} symbols, {args.days} days"))
    print(f"  Symbols: {', '.join(syms)}\n")
    print(f"  {dim('Fetching historical data...')}"),

    try:
        from feature_engine.feature_builder import FeatureBuilder
        fb = FeatureBuilder()
    except Exception:
        fb = None

    data_map: dict[str, any] = {}
    for sym in syms:
        ikey = INSTRUMENTS.get(sym)
        if not ikey:
            print(f"  {yellow(f'Unknown symbol {sym} — skipped')}")
            continue
        import requests, pandas as pd
        df = _fetch_ohlcv(token, ikey, args.days)
        if df.empty:
            print(f"  {yellow(f'{sym}: no data')}")
            continue
        if fb is not None:
            try:
                df = fb.build(df)
            except Exception:
                pass
        data_map[sym] = df
        print(f"  {dim(sym)} {green('ok')} ({len(df)} bars)")

    if not data_map:
        print(f"{R}No data loaded. Cannot tune weights.{E}")
        sys.exit(1)

    # Backtest each strategy
    strategy_classes = _get_strategy_classes()
    sharpe_map: dict[str, float] = {}

    print(f"\n  {bold('Backtesting each strategy:')}")
    print(f"  {'Strategy':<26}  {'Avg Sharpe':>12}  {'Status':>10}")
    print("  " + "─" * 56)

    for name, cls in strategy_classes.items():
        t0 = time.perf_counter()
        try:
            sharpe = _backtest_strategy(cls, cfg, data_map)
        except Exception as exc:
            print(f"  {name:<26}  {'ERROR':>12}  {dim(str(exc)[:30])}")
            sharpe = 0.0
        elapsed = time.perf_counter() - t0
        sharpe_map[name] = sharpe
        status = green("good") if sharpe >= 0.5 else (
            yellow("weak") if sharpe >= args.min_sharpe else red("drop"))
        print(f"  {name:<26}  {sharpe:>+12.3f}  {status}  {dim(f'{elapsed:.1f}s')}")

    # Normalise weights
    weights = _normalise_weights(sharpe_map, args.min_sharpe)
    enabled = [n for n, w in weights.items() if w > 0]

    print(f"\n  {bold('Proposed weights:')}")
    print(f"  {'Strategy':<26}  {'Sharpe':>10}  {'Weight':>8}")
    print("  " + "─" * 50)
    for name in sorted(weights, key=lambda n: -weights[n]):
        sh = sharpe_map.get(name, 0.0)
        w  = weights[name]
        if w > 0:
            print(f"  {name:<26}  {sh:>+10.3f}  {w:>8.3f}")
        else:
            print(f"  {dim(name):<36}  {sh:>+10.3f}  {dim('excluded')}")

    print(f"\n  Enabled strategies ({len(enabled)}): {', '.join(enabled)}")

    if args.dry_run:
        print(f"\n  {Y}Dry run — settings.yaml not modified.{E}")
        return

    _update_yaml_weights(weights, enabled)
    print(f"\n  {green('Weights written to')} {SETTINGS_FILE}")
    print(f"  Re-run with --dry-run to preview without writing.\n")


if __name__ == "__main__":
    main()
