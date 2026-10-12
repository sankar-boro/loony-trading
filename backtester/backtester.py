from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from strategies.base import BaseStrategy, Signal, SignalType
from strategies.meta_engine import MetaStrategyEngine
from utils.math_utils import sharpe_ratio, sortino_ratio, max_drawdown, profit_factor
from utils.logger import get_logger
from utils.timeutils import is_mis_squareoff_time

logger = get_logger("backtester")


@dataclass
class Trade:
    symbol: str
    direction: int
    entry_price: float
    exit_price: float
    size: float
    entry_bar: int
    exit_bar: int
    pnl: float
    strategy: str
    reason: str


@dataclass
class BacktestResult:
    trades: List[Trade]
    equity_curve: np.ndarray
    metrics: dict
    symbol: str

    def summary(self) -> str:
        m = self.metrics
        return (
            f"Symbol: {self.symbol} | Trades: {m['n_trades']} | "
            f"WinRate: {m['win_rate']:.1f}% | PF: {m['profit_factor']:.2f} | "
            f"Sharpe: {m['sharpe']:.3f} | MaxDD: {m['max_drawdown_pct']:.1f}% | "
            f"Return: {m['total_return_pct']:.2f}%"
        )


class Backtester:
    """
    Event-driven backtester with realistic slippage, commission, and latency simulation.
    Runs MetaStrategyEngine bar-by-bar on historical OHLCV data.
    """

    def __init__(self, cfg: dict, initial_capital: float = 10_000,
                 product: str = "CNC"):
        self.cfg = cfg
        self.initial_capital = initial_capital
        self.product = product  # "CNC" (delivery) or "MIS" (intraday)
        ex = cfg.get("execution", {})
        # Use per-product commission if available, else legacy fallback
        if product == "MIS":
            self.commission_pct = ex.get("commission_intraday",
                                         ex.get("commission", 0.00055))
        else:
            self.commission_pct = ex.get("commission_delivery",
                                         ex.get("commission", 0.0021))
        # commission_* settings are ROUND-TRIP costs; half is charged on
        # entry and half on exit.
        self.cost_per_side = self.commission_pct / 2
        self.slippage_pct = ex.get("slippage_pct", 0.0005)
        self.risk_per_trade = cfg.get("risk", {}).get("max_risk_per_trade", 0.01)
        self.warmup_bars = cfg.get("data", {}).get("warmup_bars", 200)

    def run(self, df: pd.DataFrame, symbol: str,
             engine: Optional[MetaStrategyEngine] = None,
             strategy: Optional[BaseStrategy] = None) -> BacktestResult:

        if engine is None and strategy is None:
            raise ValueError("Provide either engine or strategy")

        capital = self.initial_capital
        equity_curve = [capital]
        trades: List[Trade] = []
        position: Optional[dict] = None

        for i in range(self.warmup_bars, len(df)):
            window = df.iloc[:i]
            price = float(df["close"].iloc[i])

            # MIS positions get force-closed by the broker at 3:20 PM IST
            # (we simulate the controlled 3:14 PM close, same as the live
            # bot's should_squareoff_mis()) — an intraday-product backtest
            # must not let a position ride across that boundary, or its
            # results wouldn't reflect what live execution would actually
            # allow. See docs/appendix/intraday-audit.md §3/§7 item 3.
            bar_ts = df.index[i] if isinstance(df.index, pd.DatetimeIndex) else None
            mis_squareoff_now = (
                self.product == "MIS" and bar_ts is not None
                and is_mis_squareoff_time(bar_ts)
            )

            # Check open position for exit
            if position is not None:
                sl_hit = (
                    (position["direction"] == 1 and price <= position["sl"]) or
                    (position["direction"] == -1 and price >= position["sl"])
                )
                tp_hit = (
                    (position["direction"] == 1 and price >= position["tp"]) or
                    (position["direction"] == -1 and price <= position["tp"])
                )
                exit_hit = sl_hit or tp_hit or mis_squareoff_now
                if exit_hit:
                    if sl_hit:
                        reason = "stop_loss"
                    elif tp_hit:
                        reason = "take_profit"
                    else:
                        reason = "mis_squareoff"
                    exit_price = self._apply_slippage(price, -position["direction"])
                    pnl = (exit_price - position["entry"]) * position["direction"] * position["size"]
                    pnl -= self.cost_per_side * exit_price * position["size"]
                    capital += pnl
                    trades.append(Trade(
                        symbol=symbol,
                        direction=position["direction"],
                        entry_price=position["entry"],
                        exit_price=exit_price,
                        size=position["size"],
                        entry_bar=position["bar"],
                        exit_bar=i,
                        pnl=pnl,
                        strategy=position["strategy"],
                        reason=reason,
                    ))
                    position = None

            equity_curve.append(capital)

            if position is not None:
                continue

            # Don't open a fresh MIS position this late in the session —
            # live, there'd be no time left before the forced close above.
            if mis_squareoff_now:
                continue

            # Generate signal
            signal = None
            if engine is not None:
                signals = engine.generate_signals(symbol, window)
                if signals:
                    signal = engine.best_signal(signals)   # confidence × strategy weight, as the bots rank
            elif strategy is not None:
                signal = strategy.generate_signal(window, symbol)

            if signal is None or signal.signal_type not in (SignalType.BUY, SignalType.SELL):
                continue

            # Size position — cap at 25% of capital to prevent excessive leverage
            risk_amount = capital * self.risk_per_trade
            sl_dist = abs(signal.price - signal.stop_loss)
            size = risk_amount / sl_dist if sl_dist > 0 else 0
            if size <= 0:
                continue
            max_size = (capital * 0.25) / price
            size = min(size, max_size)

            entry_price = self._apply_slippage(price, signal.direction)
            entry_cost = entry_price * size * self.cost_per_side
            capital -= entry_cost

            position = {
                "direction": signal.direction,
                "entry": entry_price,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "size": size,
                "bar": i,
                "strategy": signal.strategy,
            }

        # Close any open position at end
        if position is not None:
            final_price = float(df["close"].iloc[-1])
            pnl = (final_price - position["entry"]) * position["direction"] * position["size"]
            capital += pnl
            trades.append(Trade(
                symbol=symbol, direction=position["direction"],
                entry_price=position["entry"], exit_price=final_price,
                size=position["size"], entry_bar=position["bar"],
                exit_bar=len(df) - 1, pnl=pnl,
                strategy=position["strategy"], reason="end_of_data",
            ))

        equity_arr = np.array(equity_curve)
        metrics = self._compute_metrics(trades, equity_arr)
        result = BacktestResult(trades=trades, equity_curve=equity_arr,
                                 metrics=metrics, symbol=symbol)
        logger.info(result.summary())
        return result

    def _apply_slippage(self, price: float, direction: int) -> float:
        return price * (1 + direction * self.slippage_pct)

    def _compute_metrics(self, trades: List[Trade], equity: np.ndarray) -> dict:
        n = len(trades)
        if n == 0:
            return {
                "n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "sharpe": 0.0, "sortino": 0.0, "max_drawdown_pct": 0.0,
                "total_return_pct": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "expectancy": 0.0, "cagr_pct": 0.0,
                "median_trade_return_pct": 0.0, "avg_holding_bars": 0.0,
            }
        pnls = np.array([t.pnl for t in trades])
        returns = pnls / self.initial_capital
        trade_returns_pct = np.array([
            (t.exit_price - t.entry_price) / t.entry_price * t.direction * 100 for t in trades
        ])
        holding_bars = np.array([t.exit_bar - t.entry_bar for t in trades])
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        total_return = (equity[-1] - equity[0]) / equity[0]
        n_years = len(equity) / 252 if len(equity) > 1 else 1.0
        cagr = ((1 + total_return) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0.0
        return {
            "n_trades": n,
            "win_rate": len(wins) / n * 100,
            "profit_factor": profit_factor(pnls),
            "sharpe": sharpe_ratio(returns),
            "sortino": sortino_ratio(returns),
            "max_drawdown_pct": max_drawdown(equity) * 100,
            "total_return_pct": total_return * 100,
            "cagr_pct": cagr,
            "avg_win": float(np.mean(wins)) if len(wins) else 0,
            "avg_loss": float(np.mean(losses)) if len(losses) else 0,
            "expectancy": float(np.mean(pnls)),
            "median_trade_return_pct": float(np.median(trade_returns_pct)),
            "avg_holding_bars": float(np.mean(holding_bars)),
        }

    def run_walk_forward(self, df: pd.DataFrame, symbol: str,
                          strategy: Optional[BaseStrategy] = None,
                          engine: Optional[MetaStrategyEngine] = None,
                          n_splits: int = 5) -> List[BacktestResult]:
        """Walk-forward validation to guard against overfitting."""
        results = []
        step = len(df) // n_splits
        for i in range(1, n_splits):
            test_start = i * step
            test_end = min((i + 1) * step, len(df))
            # Warm indicators up on the bars just before the split, so the
            # split itself is traded in full instead of losing warmup_bars.
            test_df = df.iloc[max(0, test_start - self.warmup_bars):test_end]
            if len(test_df) < self.warmup_bars + 10:
                continue
            r = self.run(test_df, symbol, strategy=strategy, engine=engine)
            results.append(r)
        return results
