#!/usr/bin/env python3
"""
Find cointegrated pairs within each sector of the stock universe.

For every two stocks in the same sector (config/instruments.py) it fetches
daily closes, then reports the Engle-Granger statistic, the spread's
half-life, the hedge ratio, the correlation and today's spread z-score —
the same tests PairTradingStrategy applies before it trades a pair. With
--backtest each candidate is also run through the pair backtester.

    python scripts/find_pairs.py                        # all sectors, 1 year
    python scripts/find_pairs.py --sectors Banking,IT --days 730 --backtest
    python scripts/find_pairs.py --symbols HDFCBANK,ICICIBANK,AXISBANK,KOTAKBANK

Paste the YAML it prints under `strategies:` in config/settings.yaml to
trade the pairs (see docs/engine/strategies-stat-arb.md).
"""
from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_closes(symbols: list[str], days: int) -> dict:
    from config.loader import Settings
    from data_engine.upstox import InstrumentRegistry, UpstoxAuth, UpstoxDataEngine

    cfg = Settings().as_dict()
    up = cfg.get("exchanges", {}).get("upstox", {})
    auth = UpstoxAuth(api_key=up.get("api_key", ""), api_secret=up.get("api_secret", ""),
                      redirect_uri=up.get("redirect_uri", "http://localhost:3561/callback"))
    auth.load_token()
    registry = InstrumentRegistry()
    registry.load()
    engine = UpstoxDataEngine(auth, registry)
    out = {}
    for sym in symbols:
        try:
            df = engine.fetch_ohlcv(sym, "1d", lookback_days=days)
        except Exception as exc:                       # one bad symbol must not stop the scan
            print(f"  {sym}: fetch failed ({exc})")
            continue
        if df is not None and not df.empty:
            out[sym] = df
    return out


def scan(frames: dict, groups: dict[str, list[str]], cfg: dict, backtest: bool) -> list[dict]:
    import numpy as np
    from strategies.stat_arb.pair_trading import PairTradingStrategy

    strat = PairTradingStrategy(cfg)
    rows = []
    for sector, syms in groups.items():
        for a, b in itertools.combinations([s for s in syms if s in frames], 2):
            merged = PairTradingStrategy.align(frames[a], frames[b])
            # Try both orientations; keep the one with the stronger statistic
            best = None
            for x, y, m in ((a, b, merged), (b, a, merged.rename(columns={"a": "b", "b": "a"}))):
                st = strat.evaluate(m[["a", "b"]])
                if st and (best is None or st.coint_stat < best[2].coint_stat):
                    best = (x, y, st, m)
            if best is None:
                continue
            x, y, st, m = best
            row = {"sector": sector, "a": x, "b": y, "adf": st.coint_stat, "half_life": st.half_life,
                   "beta": st.beta, "corr": float(np.corrcoef(m["a"], m["b"])[0, 1]), "z": st.z,
                   "tradable": st.tradable, "reason": st.reason}
            if backtest and st.tradable:
                from backtester.pair_backtester import run_pair_backtest
                r = run_pair_backtest(frames[x], frames[y], x, y, cfg)
                row.update(trades=r.metrics["n_trades"], ret=r.metrics["total_return_pct"],
                           sharpe=r.metrics["sharpe"])
            rows.append(row)
    return sorted(rows, key=lambda r: r["adf"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Find cointegrated pairs within sectors")
    parser.add_argument("--sectors", default="", help="Comma-separated sectors (default: all)")
    parser.add_argument("--symbols", default="", help="Only these symbols (grouped by their sector)")
    parser.add_argument("--days", type=int, default=365, help="Daily history to test (default 365)")
    parser.add_argument("--top", type=int, default=25, help="Rows to print (default 25)")
    parser.add_argument("--backtest", action="store_true", help="Backtest each tradable pair")
    args = parser.parse_args()

    from config.instruments import STOCK_UNIVERSE, get_sector_map
    from config.loader import Settings

    groups = get_sector_map()
    if args.sectors:
        wanted = {s.strip().lower() for s in args.sectors.split(",")}
        groups = {k: v for k, v in groups.items() if k.lower() in wanted}
    if args.symbols:
        only = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
        groups = {k: [s for s in v if s in only] for k, v in groups.items()}
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    symbols = sorted({s for v in groups.values() for s in v if s in STOCK_UNIVERSE})
    if not symbols:
        print("No sector has two or more of the requested symbols.")
        return 1

    print(f"Fetching {len(symbols)} symbols, {args.days} days of daily bars...")
    frames = load_closes(symbols, args.days)
    rows = scan(frames, groups, Settings().as_dict(), args.backtest)
    if not rows:
        print("Not enough data to test any pair.")
        return 1

    head = f"{'pair':<24}{'sector':<16}{'ADF':>7}{'half-life':>10}{'beta':>7}{'corr':>6}{'z':>7}"
    if args.backtest:
        head += f"{'trades':>8}{'return':>9}{'sharpe':>8}"
    print("\n" + head + "  status")
    for r in rows[:args.top]:
        line = (f"{r['a'] + '/' + r['b']:<24}{r['sector'][:15]:<16}{r['adf']:>7.2f}{r['half_life']:>10.1f}"
                f"{r['beta']:>7.2f}{r['corr']:>6.2f}{r['z']:>+7.2f}")
        if args.backtest:
            line += (f"{r['trades']:>8}{r['ret']:>8.2f}%{r['sharpe']:>8.2f}" if "trades" in r
                     else " " * 25)
        print(line + "  " + ("tradable" if r["tradable"] else r["reason"]))

    good = [r for r in rows if r["tradable"]]
    if good:
        print("\n# Add under `strategies:` in config/settings.yaml:")
        print("pairs:")
        for r in good[:5]:
            print(f"  - [{r['a']}, {r['b']}]")
    else:
        print("\nNo pair passed the cointegration and half-life tests.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
