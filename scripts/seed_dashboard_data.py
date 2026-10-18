#!/usr/bin/env python
"""
Seed Dashboard Data
===================
Runs a 180-day backtest on RELIANCE, TCS, HDFCBANK, SBIN, AXISBANK using
the existing Backtester + MetaStrategyEngine, then converts the results
into the four data files the dashboard reads.

Usage:
    cd /home/sankar/ai_projects/loony-trading
    python scripts/seed_dashboard_data.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Colour helpers ─────────────────────────────────────────────────────────────

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
C = "\033[96m"; DIM = "\033[2m"; E = "\033[0m"

def green(s):  return f"{G}{s}{E}"
def red(s):    return f"{R}{s}{E}"
def yellow(s): return f"{Y}{s}{E}"
def bold(s):   return f"{B}{s}{E}"
def dim(s):    return f"{DIM}{s}{E}"

# ── Config ────────────────────────────────────────────────────────────────────

SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "SBIN", "AXISBANK"]
from config.instruments import INSTRUMENTS as _UNIVERSE_KEYS  # noqa: E402
INSTRUMENTS = {sym: _UNIVERSE_KEYS[sym] for sym in SYMBOLS}
DAYS = 180
CAPITAL = 500_000.0

OUT_PAPER   = ROOT / "logs" / "paper_trades.jsonl"
OUT_DAILY   = ROOT / "data" / "daily_pnl.jsonl"
OUT_EQUITY  = ROOT / "data" / "equity_curve.jsonl"
OUT_POS     = ROOT / "data" / "live_positions.json"


# ── Token ──────────────────────────────────────────────────────────────────────

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


def _get_token() -> str:
    t = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
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


# ── OHLCV fetch ────────────────────────────────────────────────────────────────

def _fetch_ohlcv(token: str, ikey: str, days: int):
    import requests
    import pandas as pd

    key = ikey.replace("|", "%7C").replace(" ", "%20")
    to_d   = date.today().isoformat()
    from_d = (date.today() - timedelta(days=days)).isoformat()
    url = (f"https://api.upstox.com/v2/historical-candle/"
           f"{key}/day/{to_d}/{from_d}")

    r = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }, timeout=20)
    if r.status_code == 401:
        raise PermissionError("Token expired — run: python scripts/upstox_login.py --force")
    r.raise_for_status()

    candles = r.json().get("data", {}).get("candles", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles,
                      columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].apply(float)
    return df


# ── Engine helpers ─────────────────────────────────────────────────────────────

def _make_cfg() -> dict:
    return {
        "strategies": {"enabled": [], "weights": {}},
        "risk": {
            "max_risk_per_trade": 0.01,
            "trailing_stop_pct": 0.02,
            "max_concurrent_trades": 10,
        },
        "execution": {
            "commission": 0.001,
            "slippage_pct": 0.001,
        },
        "data": {"warmup_bars": 200},
        "system": {"mode": "paper"},
    }


# ── Aggregation helpers ────────────────────────────────────────────────────────

def _build_trade_record(t, df_index, symbol: str) -> dict:
    """Convert a backtester Trade → dashboard trade record."""
    import numpy as np
    # Get timestamps from the df index
    idx = df_index
    entry_ts = idx[t.entry_bar].isoformat() if t.entry_bar < len(idx) else ""
    exit_ts  = idx[min(t.exit_bar, len(idx) - 1)].isoformat()

    return {
        "ts":          exit_ts,
        "type":        "close",
        "symbol":      symbol,
        "direction":   int(t.direction),
        "strategy":    t.strategy,
        "entry_price": round(float(t.entry_price), 2),
        "exit_price":  round(float(t.exit_price), 2),
        "size":        round(float(t.size), 4),
        "pnl":         round(float(t.pnl), 2),
        "reason":      t.reason,
        "entry_time":  entry_ts[11:19] if len(entry_ts) >= 19 else "09:15:00",
        "exit_time":   exit_ts[11:19]  if len(exit_ts) >= 19  else "15:30:00",
    }


def _aggregate_daily(all_trade_records: list[dict]) -> list[dict]:
    """Produce one record per trading day from all trades."""
    by_day: dict[str, list] = defaultdict(list)
    for tr in all_trade_records:
        day = tr["ts"][:10]
        by_day[day].append(tr)

    days = []
    for day in sorted(by_day.keys()):
        recs = by_day[day]
        pnls = [r["pnl"] for r in recs]
        wins  = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        total = len(pnls)
        realised = sum(pnls)
        symbols_count: dict[str, float] = defaultdict(float)
        for r in recs:
            symbols_count[r["symbol"]] += abs(r["pnl"])
        top_sym = max(symbols_count, key=symbols_count.__getitem__) if symbols_count else ""

        # Max drawdown within the day (simple approximation)
        running = 0.0
        peak_running = 0.0
        max_dd = 0.0
        for p in sorted(pnls):
            running += p
            if running > peak_running:
                peak_running = running
            dd = (peak_running - running) / CAPITAL * 100 if CAPITAL else 0
            if dd > max_dd:
                max_dd = dd

        days.append({
            "date":            day,
            "realised":        round(realised, 2),
            "unrealised":      0.0,
            "trades":          total,
            "wins":            wins,
            "losses":          losses,
            "win_rate":        round(wins / max(total, 1) * 100, 1),
            "max_drawdown_pct": round(max_dd, 2),
            "top_symbol":      top_sym,
        })
    return days


def _build_equity_curve(
    all_trade_records: list[dict],
    df_dates: list,
) -> list[dict]:
    """Build one equity point per trading day."""
    # Sort trades by exit timestamp
    sorted_trades = sorted(all_trade_records, key=lambda r: r["ts"])
    equity = CAPITAL
    running_realised = 0.0
    trade_idx = 0
    points = []

    for d in sorted_trades:
        # We'll use exit timestamps
        pass

    # Simpler: one point per day that has a trade, plus start point
    day_pnl: dict[str, float] = defaultdict(float)
    for tr in sorted_trades:
        day_pnl[tr["ts"][:10]] += tr["pnl"]

    # Fill gaps with neutral days
    if not day_pnl:
        return []

    all_days = sorted(day_pnl.keys())
    start_day = (
        datetime.fromisoformat(all_days[0]) - timedelta(days=1)
    ).date().isoformat()

    # Starting point
    points.append({
        "ts":          f"{start_day}T09:15:00",
        "equity":      round(CAPITAL, 2),
        "cash":        round(CAPITAL, 2),
        "realised":    0.0,
        "unrealised":  0.0,
        "open_pos":    0,
    })

    cumulative = 0.0
    for day in all_days:
        cumulative += day_pnl[day]
        eq = CAPITAL + cumulative
        points.append({
            "ts":          f"{day}T15:30:00",
            "equity":      round(eq, 2),
            "cash":        round(eq, 2),
            "realised":    round(cumulative, 2),
            "unrealised":  0.0,
            "open_pos":    0,
        })
    return points


def _build_live_positions(
    all_trade_records: list[dict],
    last_open_trades: list[dict],
    equity_points: list[dict],
    signal_log: list[dict],
) -> dict:
    """Build live_positions.json snapshot."""
    # Last 10 closed trades
    closed_10 = sorted(all_trade_records, key=lambda r: r["ts"])[-10:]
    latest_eq  = equity_points[-1] if equity_points else {}
    cash       = latest_eq.get("equity", CAPITAL)

    return {
        "saved_at":       int(time.time()),
        "initial_capital": CAPITAL,
        "cash":           round(cash - sum(
            p["entry_price"] * p["size"] for p in last_open_trades
        ), 2),
        "positions":      last_open_trades,
        "closed_trades":  closed_10,
        "signal_log":     signal_log[-20:] if signal_log else [],
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    _load_env()
    token = _get_token()
    if not token:
        print(f"\n{R}No Upstox token found.{E}  Run: python scripts/upstox_login.py")
        sys.exit(1)

    print(bold(f"\n  Seed Dashboard Data"))
    print(f"  Symbols  : {', '.join(SYMBOLS)}")
    print(f"  Period   : {DAYS} days  •  Capital: ₹{CAPITAL:,.0f}")
    print("  " + "═" * 60)

    try:
        from feature_engine.feature_builder import FeatureBuilder
        from backtester.backtester import Backtester
        from strategies.meta_engine import MetaStrategyEngine
    except Exception as exc:
        print(f"{R}Failed to import engine: {exc}{E}")
        sys.exit(1)

    cfg    = _make_cfg()
    engine = MetaStrategyEngine(cfg)
    fb     = FeatureBuilder()
    bt     = Backtester(cfg, initial_capital=CAPITAL, product="CNC")

    print(f"  {dim(f'Engine ready — {len(engine.strategies)} strategies')}")

    all_trade_records: list[dict] = []
    last_open_positions: list[dict] = []
    signal_log_entries: list[dict] = []
    all_dfs: dict = {}

    for sym in SYMBOLS:
        ikey = INSTRUMENTS[sym]
        print(f"\n  {dim(f'Fetching {sym}...')} ", end="", flush=True)

        try:
            df_raw = _fetch_ohlcv(token, ikey, DAYS + 300)   # +~200 trading days for warmup_bars
        except PermissionError as exc:
            print(f"{R}{exc}{E}")
            sys.exit(1)
        except Exception as exc:
            print(f"{Y}Failed: {exc}{E}")
            continue

        if df_raw.empty or len(df_raw) < 80:
            print(f"{Y}Skipped — only {len(df_raw)} bars{E}")
            continue

        print(f"{dim(f'{len(df_raw)} bars')} → ", end="", flush=True)

        try:
            df = fb.build(df_raw)
        except Exception:
            df = df_raw

        print(f"{dim('running...')} ", end="", flush=True)
        try:
            result = bt.run(df, sym, engine=engine)
        except Exception as exc:
            print(f"{Y}Backtest failed: {exc}{E}")
            continue

        m = result.metrics
        print(
            f"done — {len(result.trades)} trades  "
            f"ret={m.get('total_return_pct', 0):+.1f}%  "
            f"wr={m.get('win_rate', 0):.0f}%"
        )

        # Convert trades — keep last 2-3 as "open" positions
        df_index = df.index.tolist()
        all_closed = result.trades[:-2] if len(result.trades) > 3 else result.trades
        open_trades_raw = result.trades[-2:] if len(result.trades) > 3 else []

        for t in all_closed:
            rec = _build_trade_record(t, df_index, sym)
            all_trade_records.append(rec)
            # Also add a BUY signal entry
            signal_log_entries.append({
                "time":       rec["entry_time"],
                "type":       "BUY" if t.direction == 1 else "SELL",
                "symbol":     sym,
                "price":      rec["entry_price"],
                "size":       round(rec["size"]),
                "strategy":   rec["strategy"],
                "confidence": round(0.5 + 0.4 * abs(rec["pnl"]) / (CAPITAL * 0.01 + 1), 2),
            })
            signal_log_entries.append({
                "time":     rec["exit_time"],
                "type":     "CLOSE",
                "symbol":   sym,
                "price":    rec["exit_price"],
                "size":     round(rec["size"]),
                "pnl":      rec["pnl"],
                "strategy": rec["strategy"],
                "reason":   rec["reason"],
            })

        # Build open positions from last 2 raw trades
        last_price = float(df["close"].iloc[-1])
        for t in open_trades_raw:
            ep = float(t.entry_price)
            unreal = (last_price - ep) * t.direction * t.size
            sl  = ep * (1 - 0.025 * t.direction)
            tp  = ep * (1 + 0.055 * t.direction)
            last_open_positions.append({
                "symbol":          sym,
                "direction":       int(t.direction),
                "size":            round(float(t.size), 4),
                "entry_price":     round(ep, 2),
                "stop_loss":       round(sl, 2),
                "take_profit":     round(tp, 2),
                "trailing_stop_pct": 0.02,
                "strategy":        t.strategy,
                "entry_time":      "09:22:00",
                "peak_price":      round(last_price, 2),
                "current_price":   round(last_price, 2),
                "unrealised_pnl":  round(unreal, 2),
            })

        all_dfs[sym] = df

    if not all_trade_records:
        print(f"\n{Y}Warning: no trades generated. Check token / data.{E}")
        # Write minimal placeholder files so the dashboard doesn't 404
        all_trade_records = []

    # ── Write paper_trades.jsonl ──────────────────────────────────────────────

    all_trade_records.sort(key=lambda r: r["ts"])
    OUT_PAPER.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PAPER.open("w", encoding="utf-8") as f:
        for rec in all_trade_records:
            f.write(json.dumps(rec) + "\n")
    print(f"\n  {green('✓')} {OUT_PAPER}  ({len(all_trade_records)} trades)")

    # ── Write daily_pnl.jsonl ─────────────────────────────────────────────────

    daily_records = _aggregate_daily(all_trade_records)
    OUT_DAILY.parent.mkdir(parents=True, exist_ok=True)
    with OUT_DAILY.open("w", encoding="utf-8") as f:
        for dr in daily_records:
            f.write(json.dumps(dr) + "\n")
    print(f"  {green('✓')} {OUT_DAILY}  ({len(daily_records)} days)")

    # ── Write equity_curve.jsonl ──────────────────────────────────────────────

    equity_points = _build_equity_curve(all_trade_records, [])
    OUT_EQUITY.parent.mkdir(parents=True, exist_ok=True)
    with OUT_EQUITY.open("w", encoding="utf-8") as f:
        for ep in equity_points:
            f.write(json.dumps(ep) + "\n")
    print(f"  {green('✓')} {OUT_EQUITY}  ({len(equity_points)} points)")

    # ── Write live_positions.json ─────────────────────────────────────────────

    live_snap = _build_live_positions(
        all_trade_records,
        last_open_positions[:3],
        equity_points,
        signal_log_entries,
    )
    OUT_POS.parent.mkdir(parents=True, exist_ok=True)
    OUT_POS.write_text(json.dumps(live_snap, indent=2), encoding="utf-8")
    pos_count = len(live_snap["positions"])
    print(f"  {green('✓')} {OUT_POS}  ({pos_count} open positions)")

    # ── Summary ───────────────────────────────────────────────────────────────

    total_pnl = sum(r["pnl"] for r in all_trade_records)
    wins  = sum(1 for r in all_trade_records if r["pnl"] > 0)
    total = len(all_trade_records)
    print()
    print(bold("  Summary"))
    print(f"  Total trades : {total}")
    print(f"  Win rate     : {wins / max(total, 1) * 100:.1f}%")
    print(f"  Total P&L    : ₹{total_pnl:+,.0f}")
    print(f"  Trading days : {len(daily_records)}")
    if equity_points:
        final_eq = equity_points[-1]["equity"]
        ret_pct  = (final_eq - CAPITAL) / CAPITAL * 100
        print(f"  Final equity : ₹{final_eq:,.0f}  ({ret_pct:+.2f}%)")
    print()
    print(f"  {green('Done!')}  Dashboard data seeded successfully.\n")


if __name__ == "__main__":
    main()
