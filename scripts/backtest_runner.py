#!/usr/bin/env python
"""
Backtest Runner
===============

Fetches live Upstox OHLCV data and runs the full event-driven backtester.
Exercises the entire stack: Upstox API → FeatureBuilder → MetaStrategyEngine →
Backtester → BacktestResult with metrics + trade log.

Usage:
    python scripts/backtest_runner.py
    python scripts/backtest_runner.py --symbol RELIANCE
    python scripts/backtest_runner.py --symbols RELIANCE,TCS,HDFCBANK
    python scripts/backtest_runner.py --days 180 --capital 500000
    python scripts/backtest_runner.py --strategies ema_crossover,rsi_reversion
    python scripts/backtest_runner.py --timeframe 1d
    python scripts/backtest_runner.py --monte-carlo        # bootstrap tail risk
    python scripts/backtest_runner.py --walk-forward       # walk-forward splits
    python scripts/backtest_runner.py --trades             # print every trade
    python scripts/backtest_runner.py --equity-curve       # ASCII equity curve
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

# ── Colour helpers ────────────────────────────────────────────────────────────

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
C = "\033[96m"; DIM = "\033[2m"; E = "\033[0m"

def green(s):  return f"{G}{s}{E}"
def red(s):    return f"{R}{s}{E}"
def yellow(s): return f"{Y}{s}{E}"
def bold(s):   return f"{B}{s}{E}"
def dim(s):    return f"{DIM}{s}{E}"
def cyan(s):   return f"{C}{s}{E}"

def pnl_s(v: float) -> str:
    s = f"₹{v:>+12,.2f}"
    return green(s) if v > 0 else (red(s) if v < 0 else s)

def pct_s(v: float) -> str:
    s = f"{v:>+7.2f}%"
    return green(s) if v > 0 else (red(s) if v < 0 else s)


# ── Instrument registry ───────────────────────────────────────────────────────

INSTRUMENTS: dict[str, str] = {
    "NIFTY50":    "NSE_INDEX|Nifty 50",
    "NIFTY":      "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
    "FINNIFTY":   "NSE_INDEX|Nifty Fin Service",
    "RELIANCE":   "NSE_EQ|INE002A01018",
    "TCS":        "NSE_EQ|INE467B01029",
    "HDFCBANK":   "NSE_EQ|INE040A01034",
    "INFY":       "NSE_EQ|INE009A01021",
    "ICICIBANK":  "NSE_EQ|INE090A01021",
    "SBIN":       "NSE_EQ|INE062A01020",
    "BAJFINANCE": "NSE_EQ|INE296A01024",
    "BHARTIARTL": "NSE_EQ|INE397D01024",
    "KOTAKBANK":  "NSE_EQ|INE237A01028",
    "LT":         "NSE_EQ|INE018A01030",
    "AXISBANK":   "NSE_EQ|INE238A01034",
    "WIPRO":      "NSE_EQ|INE075A01022",
    "TATAMOTORS": "NSE_EQ|INE155A01022",
    "HCLTECH":    "NSE_EQ|INE860A01027",
    "ITC":        "NSE_EQ|INE154A01025",
    "SUNPHARMA":  "NSE_EQ|INE044A01036",
    "ONGC":       "NSE_EQ|INE213A01029",
    "MARUTI":     "NSE_EQ|INE585B01010",
    "TITAN":      "NSE_EQ|INE280A01028",
    "HINDUNILVR": "NSE_EQ|INE030A01027",
    "ASIANPAINT": "NSE_EQ|INE021A01026",
}

DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]

_TF_CONFIG = {
    "1d":  ("day",      365),
    "1h":  ("60minute", 90),
    "30m": ("30minute", 60),
    "15m": ("15minute", 45),
}


# ── Token loading ─────────────────────────────────────────────────────────────

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


def _get_token(explicit: str = None) -> str:
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


# ── Data fetching ─────────────────────────────────────────────────────────────

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
            timeout=15,
        )
        if r.status_code == 401:
            raise PermissionError("Token expired — run: python scripts/upstox_login.py --force")
        r.raise_for_status()
        candles = r.json().get("data", {}).get("candles", [])
    except PermissionError:
        raise
    except Exception as e:
        return pd.DataFrame()

    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].apply(float)
    return df


# ── Engine bootstrap ──────────────────────────────────────────────────────────

def _make_cfg(strategies: list[str], capital: float) -> dict:
    try:
        from config.loader import Settings
        cfg = Settings().as_dict()
    except Exception:
        cfg = {}
    # Override fields relevant to backtesting
    if strategies:
        cfg.setdefault("strategies", {})["enabled"] = strategies
    cfg["system"] = {"mode": "backtest"}
    cfg.setdefault("risk", {}).update({
        "max_risk_per_trade": cfg.get("risk", {}).get("max_risk_per_trade", 0.01),
        "trailing_stop_pct":  cfg.get("risk", {}).get("trailing_stop_pct", 0.02),
    })
    return cfg


# ── ASCII equity curve ────────────────────────────────────────────────────────

def _ascii_equity_curve(curve: "np.ndarray", width: int = 70, height: int = 12,
                         initial: float = 0) -> str:
    import numpy as np
    if len(curve) < 2:
        return "  (not enough data for curve)"

    lo, hi = float(np.min(curve)), float(np.max(curve))
    if hi == lo:
        return "  (flat equity — no trades)"

    lines = []
    for row in range(height):
        threshold = hi - (hi - lo) * row / (height - 1)
        row_chars = []
        for col in range(width):
            idx = int(col / width * (len(curve) - 1))
            val = curve[idx]
            if val >= threshold:
                row_chars.append("█")
            else:
                row_chars.append(" ")
        pct = (threshold - initial) / initial * 100 if initial else 0
        label = f" {pct:>+6.1f}%" if row in (0, height - 1) else ""
        lines.append("  │" + "".join(row_chars) + label)

    # x-axis
    lines.append("  └" + "─" * width)
    start_d = "start"
    end_d = "now"
    lines.append(f"   {start_d:<{width//2}}{end_d:>{width//2}}")
    return "\n".join(lines)


# ── Result display ────────────────────────────────────────────────────────────

def _compute_benchmark(strategy_curve, benchmark_df) -> dict:
    """
    Compute alpha, beta, and information ratio vs Nifty 50.
    strategy_curve : np.ndarray of portfolio values (length N+1)
    benchmark_df   : DataFrame with 'close' column, same date range
    """
    import numpy as np

    if benchmark_df is None or benchmark_df.empty or len(strategy_curve) < 2:
        return {}

    strat_vals = np.array(strategy_curve, dtype=float)
    strat_rets = np.diff(strat_vals) / strat_vals[:-1]

    bench_close = benchmark_df["close"].values.astype(float)
    # Align lengths
    n = min(len(strat_rets), len(bench_close) - 1)
    strat_rets  = strat_rets[-n:]
    bench_rets  = np.diff(bench_close)[-n:] / bench_close[-n-1:-1]

    if len(strat_rets) < 5:
        return {}

    bench_total_ret  = (bench_close[-1] / bench_close[0] - 1) * 100
    strat_total_ret  = (strat_vals[-1]  / strat_vals[0]  - 1) * 100

    cov_mat = np.cov(strat_rets, bench_rets)
    beta    = cov_mat[0, 1] / cov_mat[1, 1] if cov_mat[1, 1] != 0 else 0.0
    alpha   = strat_total_ret - beta * bench_total_ret

    # Information Ratio = active return / tracking error
    active_rets = strat_rets - bench_rets
    te = float(np.std(active_rets)) * (252 ** 0.5) if len(active_rets) > 1 else 0.0
    ir = (alpha / te) if te != 0 else 0.0

    return {
        "bench_return_pct": round(bench_total_ret, 2),
        "strat_return_pct": round(strat_total_ret, 2),
        "alpha_pct":        round(alpha, 2),
        "beta":             round(beta, 3),
        "info_ratio":       round(ir, 3),
    }


def _print_result(result, symbol: str, capital: float,
                  show_trades: bool, show_curve: bool, days: int,
                  from_date: str, to_date: str,
                  benchmark_df=None):
    import numpy as np

    m = result.metrics
    trades = result.trades
    curve = result.equity_curve

    print(bold(f"\n  ── {symbol} ─────────────────────────────────────────────────────"))
    print(f"  Period   : {from_date}  →  {to_date}  ({days} days)")
    print(f"  Capital  : ₹{capital:,.0f}  →  ₹{curve[-1]:,.0f}" if len(curve) > 0 else "")
    print()

    # Core metrics
    total_ret = m.get("total_return_pct", 0.0)
    print(f"  {'Total Return':<22}  {pct_s(total_ret)}")
    print(f"  {'CAGR':<22}  {pct_s(m.get('cagr_pct', total_ret))}")
    print(f"  {'Sharpe Ratio':<22}  {m.get('sharpe', 0.0):>8.3f}")
    print(f"  {'Sortino Ratio':<22}  {m.get('sortino', 0.0):>8.3f}")
    dd_pct = m.get("max_drawdown_pct", 0.0)
    print(f"  {'Max Drawdown':<22}  {red(f'{dd_pct:>+7.2f}%')}")

    # Benchmark comparison
    bm = _compute_benchmark(curve, benchmark_df)
    if bm:
        alpha_pct = bm["alpha_pct"]
        print()
        print(f"  {dim('── vs Nifty 50 ─────────────────────────────────────────────────')}")
        print(f"  {'Nifty 50 Return':<22}  {pct_s(bm['bench_return_pct'])}")
        print(f"  {'Strategy Return':<22}  {pct_s(bm['strat_return_pct'])}")
        alpha_str = green(f"{alpha_pct:>+7.2f}%") if alpha_pct > 0 else red(f"{alpha_pct:>+7.2f}%")
        print(f"  {'Alpha (vs Nifty)':<22}  {alpha_str}")
        print(f"  {'Beta':<22}  {bm['beta']:>8.3f}")
        print(f"  {'Information Ratio':<22}  {bm['info_ratio']:>8.3f}")
    print()

    # Trade stats
    n = m.get("n_trades", len(trades))
    wr = m.get("win_rate", 0.0)
    pf = m.get("profit_factor", 0.0)
    avg_win  = m.get("avg_win", 0.0)
    avg_loss = m.get("avg_loss", 0.0)
    print(f"  {'Trades':<22}  {n:>8}")
    print(f"  {'Win Rate':<22}  {wr:>7.1f}%")
    print(f"  {'Profit Factor':<22}  {pf:>8.2f}")
    if avg_win:  print(f"  {'Avg Win':<22}  {pnl_s(avg_win)}")
    if avg_loss: print(f"  {'Avg Loss':<22}  {pnl_s(avg_loss)}")
    print()

    # Strategy breakdown
    if trades:
        from collections import Counter
        strat_counts = Counter(t.strategy for t in trades)
        strat_pnl: dict[str, float] = {}
        for t in trades:
            strat_pnl[t.strategy] = strat_pnl.get(t.strategy, 0.0) + t.pnl
        print(f"  Strategy Breakdown:")
        for strat, count in strat_counts.most_common():
            pnl_val = strat_pnl.get(strat, 0.0)
            print(f"    {strat:<30}  {count:>4} trades  {pnl_s(pnl_val)}")
        print()

    if show_curve and len(curve) > 0:
        print(f"  Equity Curve (₹{curve[0]:,.0f} → ₹{curve[-1]:,.0f}):")
        print(_ascii_equity_curve(curve, initial=capital))
        print()

    if show_trades and trades:
        print(f"  Trade Log ({len(trades)} trades):")
        print(f"  {'#':>4}  {'Dir':<6}  {'Entry':>12}  {'Exit':>12}  "
              f"{'Size':>8}  {'P&L':>14}  {'Bars':>5}  Strategy")
        print("  " + "─" * 90)
        for i, t in enumerate(trades[:50], 1):
            dir_s = green("LONG ") if t.direction == 1 else red("SHORT")
            dur = t.exit_bar - t.entry_bar
            print(f"  {i:>4}  {dir_s}  ₹{t.entry_price:>10,.2f}  ₹{t.exit_price:>10,.2f}  "
                  f"{t.size:>8.1f}  {pnl_s(t.pnl)}  {dur:>5}  {t.strategy}")
        if len(trades) > 50:
            print(f"  {dim(f'... and {len(trades)-50} more trades')}")
        print()


def _print_portfolio_summary(all_results: list[tuple[str, object]], capital: float,
                              benchmark_df=None):
    import numpy as np
    if not all_results:
        return

    print(bold("\n  ── Portfolio Summary ──────────────────────────────────────────────"))
    print(f"  {'Symbol':<14}  {'Return':>8}  {'Sharpe':>7}  {'MaxDD':>8}  "
          f"{'Trades':>7}  {'Win%':>6}  {'PF':>6}")
    print("  " + "─" * 72)

    total_pnl = 0.0
    for sym, res in all_results:
        m = res.metrics
        ret = m.get("total_return_pct", 0.0)
        sharpe = m.get("sharpe", 0.0)
        dd = m.get("max_drawdown_pct", 0.0)
        n = m.get("n_trades", 0)
        wr = m.get("win_rate", 0.0)
        pf = m.get("profit_factor", 0.0)
        pnl = (ret / 100) * capital
        total_pnl += pnl
        print(f"  {sym:<14}  {pct_s(ret)}  {sharpe:>7.2f}  "
              f"{red(f'{dd:>+7.1f}%')}  {n:>7}  {wr:>5.1f}%  {pf:>6.2f}")

    print("  " + "─" * 72)
    avg_ret = sum(r.metrics.get("total_return_pct", 0) for _, r in all_results) / len(all_results)
    print(f"  {'AVERAGE':<14}  {pct_s(avg_ret)}")
    print(f"\n  Hypothetical combined P&L (equal-weight): {pnl_s(total_pnl / len(all_results))}")

    # Benchmark summary row
    if benchmark_df is not None and not benchmark_df.empty:
        import numpy as np
        bc = benchmark_df["close"].values.astype(float)
        bench_ret = (bc[-1] / bc[0] - 1) * 100 if bc[0] != 0 else 0.0
        beat = sum(1 for _, r in all_results
                   if r.metrics.get("total_return_pct", 0) > bench_ret)
        alpha_col = green(f"{avg_ret - bench_ret:>+7.2f}%") \
                    if avg_ret > bench_ret else red(f"{avg_ret - bench_ret:>+7.2f}%")
        print(f"\n  Nifty 50 benchmark return : {pct_s(bench_ret)}")
        print(f"  Avg strategy alpha        : {alpha_col}")
        print(f"  Strategies beating Nifty  : {beat}/{len(all_results)}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest runner using live Upstox data")
    parser.add_argument("--symbol",      help="Single symbol (overrides --symbols)")
    parser.add_argument("--symbols",     default="",
                        help="Comma-separated symbols (default: top 5 Nifty50)")
    parser.add_argument("--days",        type=int, default=365,
                        help="Lookback days (default: 365)")
    parser.add_argument("--capital",     type=float, default=500_000,
                        help="Initial capital in ₹ (default: 5,00,000)")
    parser.add_argument("--timeframe",   default="1d",
                        choices=list(_TF_CONFIG.keys()))
    parser.add_argument("--strategies",  default="",
                        help="Comma-separated strategy names to enable (default: all)")
    parser.add_argument("--monte-carlo", action="store_true",
                        help="Run Monte Carlo simulation on backtest results")
    parser.add_argument("--walk-forward", action="store_true",
                        help="Run walk-forward splits instead of full backtest")
    parser.add_argument("--trades",      action="store_true",
                        help="Print full trade log for each symbol")
    parser.add_argument("--equity-curve", action="store_true",
                        help="Print ASCII equity curve")
    parser.add_argument("--token",       help="Explicit access token")
    args = parser.parse_args()

    _load_env()
    token = _get_token(args.token)
    if not token:
        print(f"\n{R}No token found.{E}  Run: python scripts/upstox_login.py")
        sys.exit(1)

    # Resolve symbols
    if args.symbol:
        raw = [args.symbol.strip().upper()]
    elif args.symbols:
        raw = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        raw = DEFAULT_SYMBOLS

    resolved: list[tuple[str, str]] = []
    for sym in raw:
        key = INSTRUMENTS.get(sym)
        if key:
            resolved.append((sym, key))
        else:
            print(f"{Y}Unknown symbol '{sym}' — skipped.{E}")

    if not resolved:
        print(f"{R}No valid symbols.{E}")
        sys.exit(1)

    interval, _ = _TF_CONFIG[args.timeframe]
    days = args.days
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]

    cfg = _make_cfg(strategies, args.capital)

    # Load engine
    print(f"\n{DIM}Loading strategy engine...{E}", end="", flush=True)
    try:
        from strategies.meta_engine import MetaStrategyEngine
        from feature_engine.feature_builder import FeatureBuilder
        from backtester.backtester import Backtester
        engine = MetaStrategyEngine(cfg)
        fb = FeatureBuilder()
        bt = Backtester(cfg, initial_capital=args.capital)
        print(f"\r{DIM}Engine ready — {len(engine.strategies)} strategies{E}            ")
    except Exception as e:
        print(f"\n{R}Failed to load engine: {e}{E}")
        sys.exit(1)

    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=days)).isoformat()

    print(bold(f"\n  Backtest Runner  •  {from_date} → {to_date}  •  "
               f"Capital: ₹{args.capital:,.0f}  •  TF:{args.timeframe}"))
    print("  " + "═" * 70)

    all_results: list[tuple[str, object]] = []

    # Fetch Nifty 50 benchmark once for the same period
    print(f"  {dim('Fetching Nifty 50 benchmark...')} ", end="", flush=True)
    benchmark_df = _fetch_ohlcv(token, "NSE_INDEX|Nifty 50", interval, days)
    if not benchmark_df.empty:
        print(f"{dim(f'{len(benchmark_df)} bars')}")
    else:
        print(f"{Y}unavailable — benchmark comparison disabled{E}")
        benchmark_df = None

    for sym, ikey in resolved:
        print(f"\n  {dim(f'Fetching {sym}...')} ", end="", flush=True)
        t0 = time.perf_counter()

        df_raw = _fetch_ohlcv(token, ikey, interval, days)
        if df_raw.empty or len(df_raw) < 80:
            print(f"{Y}Skipped — only {len(df_raw)} bars (need 80+){E}")
            continue

        print(f"{dim(f'{len(df_raw)} bars')} ", end="", flush=True)

        try:
            df = fb.build(df_raw)
        except Exception as e:
            print(f"{Y}FeatureBuilder failed: {e}{E}")
            df = df_raw

        if len(df) < 60:
            print(f"{Y}Skipped — {len(df)} bars after features{E}")
            continue

        print(f"→ {dim('running backtest...')} ", end="", flush=True)

        try:
            if args.walk_forward:
                wf_results = bt.run_walk_forward(df, sym, engine=engine)
                elapsed = time.perf_counter() - t0

                print(f"done ({elapsed:.1f}s)")
                print(f"\n  {bold(sym)} Walk-Forward ({len(wf_results)} splits):")
                for split_i, wfr in enumerate(wf_results, 1):
                    m = wfr.metrics
                    wf_dd = m.get("max_drawdown_pct", 0)
                    print(f"    Split {split_i:>2}:  "
                          f"return={pct_s(m.get('total_return_pct', 0))}"
                          f"  sharpe={m.get('sharpe', 0):.2f}"
                          f"  maxdd={red(f'{wf_dd:+.1f}%')}"
                          f"  trades={m.get('n_trades', 0)}")
                if wf_results:
                    all_results.append((sym, wf_results[-1]))
            else:
                result = bt.run(df, sym, engine=engine)
                elapsed = time.perf_counter() - t0
                print(f"done ({elapsed:.1f}s)")
                _print_result(result, sym, args.capital, args.trades,
                               args.equity_curve, days, from_date, to_date,
                               benchmark_df=benchmark_df)

                if args.monte_carlo and result.trades:
                    try:
                        from backtester.monte_carlo import run_monte_carlo
                        pnl_list = [t.pnl for t in result.trades]
                        mc = run_monte_carlo(pnl_list, n_simulations=500, method="bootstrap")
                        print(f"  {bold('Monte Carlo')} (500 sims on {len(pnl_list)} trades):")
                        print(f"    Sharpe   mean={mc.sharpe_mean:.2f}  "
                              f"5th={mc.sharpe_p5:.2f}  95th={mc.sharpe_p95:.2f}")
                        print(f"    MaxDD    mean={mc.max_dd_mean:.1f}%  "
                              f"worst={mc.max_dd_p95:.1f}%")
                        print(f"    Return   mean={pct_s(mc.return_mean)}")
                        print(f"    P(Sharpe>1): {mc.p_value_sharpe*100:.1f}%")
                        print()
                    except Exception as e:
                        print(f"  {Y}Monte Carlo failed: {e}{E}")

                all_results.append((sym, result))

        except Exception as e:
            print(f"\n  {Y}Backtest failed for {sym}: {e}{E}")

    if len(all_results) > 1:
        _print_portfolio_summary(all_results, args.capital, benchmark_df=benchmark_df)


if __name__ == "__main__":
    main()
