"""
Backtest one pair with PairTradingStrategy: both legs open and close
together, sized beta-neutral, managed on the spread's z-score.

On each bar the strategy is evaluated on the aligned closes up to and
including that bar (it is stateless, so this never sees the future), and
any entry or exit fills at that bar's close with slippage against you.
Each leg pays `execution.commission_futures` (round trip, half per side),
because holding a short leg overnight in India means futures.

    from backtester.pair_backtester import run_pair_backtest
    result = run_pair_backtest(df_hdfc, df_icici, "HDFCBANK", "ICICIBANK", cfg)
    print(result.summary())
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from backtester.backtester import Backtester, BacktestResult, Trade
from strategies.stat_arb.pair_trading import PairState, PairTradingStrategy


@dataclass
class PairTrade:
    position: int            # +1 long A / short B, −1 short A / long B
    qty_a: int
    qty_b: int
    entry_a: float
    entry_b: float
    exit_a: float
    exit_b: float
    entry_bar: int
    exit_bar: int
    entry_z: float
    exit_z: float
    pnl: float               # after costs
    reason: str


def _leg_fill(price: float, side: int, slippage: float) -> float:
    """Fill price for buying (side +1) or selling (−1) with slippage against you."""
    return price * (1 + side * slippage)


def run_pair_backtest(df_a: pd.DataFrame, df_b: pd.DataFrame, sym_a: str, sym_b: str,
                      cfg: dict, initial_capital: float = 500_000) -> BacktestResult:
    strat = PairTradingStrategy(cfg)
    ex = cfg.get("execution", {}) or {}
    cost_side = float(ex.get("commission_futures", 0.0006)) / 2
    slip = float(ex.get("slippage_pct", 0.0005))

    merged = PairTradingStrategy.align(df_a, df_b)
    a = merged["a"].to_numpy(dtype=float)
    b = merged["b"].to_numpy(dtype=float)

    capital = initial_capital
    equity = [capital]
    pair_trades: List[PairTrade] = []
    open_: Optional[dict] = None

    def close(i: int, state: PairState, reason: str) -> float:
        p = open_["position"]
        exit_a = _leg_fill(a[i], -p, slip)           # A was bought if p = +1: now sell
        exit_b = _leg_fill(b[i], p, slip)
        gross = (p * (exit_a - open_["entry_a"]) * open_["qty_a"]
                 - p * (exit_b - open_["entry_b"]) * open_["qty_b"])
        costs = cost_side * (exit_a * open_["qty_a"] + exit_b * open_["qty_b"])
        pnl = gross - costs
        pair_trades.append(PairTrade(
            position=p, qty_a=open_["qty_a"], qty_b=open_["qty_b"],
            entry_a=open_["entry_a"], entry_b=open_["entry_b"], exit_a=exit_a, exit_b=exit_b,
            entry_bar=open_["bar"], exit_bar=i, entry_z=open_["z"], exit_z=state.z,
            pnl=pnl, reason=reason))
        return pnl

    for i in range(strat.min_history, len(merged)):
        state = strat.evaluate(merged.iloc[:i + 1])
        if state is None:
            equity.append(capital)
            continue
        if open_ is not None:
            reason = strat.exit_reason(state, open_["position"], i - open_["bar"])
            if reason is None and i == len(merged) - 1:
                reason = "end_of_data"
            if reason:
                capital += close(i, state, reason)
                open_ = None
        elif i < len(merged) - 1:
            sides = state.entry_sides(strat.entry_z)
            if sides:
                p = 1 if sides[0].value == "buy" else -1
                qty_a, qty_b = strat.leg_quantities(state, a[i], capital)
                if qty_a > 0 and qty_b > 0:
                    entry_a = _leg_fill(a[i], p, slip)
                    entry_b = _leg_fill(b[i], -p, slip)
                    capital -= cost_side * (entry_a * qty_a + entry_b * qty_b)
                    open_ = {"position": p, "qty_a": qty_a, "qty_b": qty_b, "entry_a": entry_a,
                             "entry_b": entry_b, "bar": i, "z": state.z}
        equity.append(capital)

    # Report through the common metrics: a pair trade's "price" is its gross
    # notional at entry, so per-trade return = P&L / gross notional.
    trades = [Trade(symbol=f"{sym_a}/{sym_b}", direction=1,
                    entry_price=t.entry_a * t.qty_a + t.entry_b * t.qty_b,
                    exit_price=t.entry_a * t.qty_a + t.entry_b * t.qty_b + t.pnl,
                    size=1, entry_bar=t.entry_bar, exit_bar=t.exit_bar, pnl=t.pnl,
                    strategy=strat.name, reason=t.reason) for t in pair_trades]
    bt = Backtester(cfg, initial_capital=initial_capital)
    eq = np.array(equity)
    result = BacktestResult(trades=trades, equity_curve=eq,
                            metrics=bt._compute_metrics(trades, eq), symbol=f"{sym_a}/{sym_b}")
    result.pair_trades = pair_trades          # leg-level detail
    return result
