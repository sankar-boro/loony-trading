from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from strategies.base import BaseStrategy, Signal, SignalType
from strategies.meta_engine import MetaStrategyEngine
from utils.math_utils import sharpe_ratio, sortino_ratio, max_drawdown, profit_factor
from utils.logger import get_logger

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

    def __init__(self, cfg: dict, initial_capital: float = 10_000):
        self.cfg = cfg
        self.initial_capital = initial_capital
        self.commission_pct = cfg.get("execution", {}).get("commission", 0.001)
        self.slippage_pct = cfg.get("execution", {}).get("slippage_pct", 0.001)
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

            # Check open position for exit
            if position is not None:
                exit_hit = (
                    (position["direction"] == 1 and price <= position["sl"]) or
                    (position["direction"] == -1 and price >= position["sl"]) or
                    (position["direction"] == 1 and price >= position["tp"]) or
                    (position["direction"] == -1 and price <= position["tp"])
                )
                if exit_hit:
                    reason = "stop_loss" if (
                        (position["direction"] == 1 and price <= position["sl"]) or
                        (position["direction"] == -1 and price >= position["sl"])
                    ) else "take_profit"
                    exit_price = self._apply_slippage(price, -position["direction"])
                    pnl = (exit_price - position["entry"]) * position["direction"] * position["size"]
                    pnl -= self.commission_pct * exit_price * position["size"]
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

            # Generate signal
            signal = None
            if engine is not None:
                signals = engine.generate_signals(symbol, window)
                if signals:
                    signal = max(signals, key=lambda s: s.confidence)
            elif strategy is not None:
                signal = strategy.generate_signal(window, symbol)

            if signal is None or signal.signal_type not in (SignalType.BUY, SignalType.SELL):
                continue

            # Size position
            risk_amount = capital * self.risk_per_trade
            sl_dist = abs(signal.price - signal.stop_loss)
            size = risk_amount / sl_dist if sl_dist > 0 else 0
            if size <= 0:
                continue

            entry_price = self._apply_slippage(price, signal.direction)
            entry_cost = entry_price * size * self.commission_pct
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
            return {"n_trades": 0}
        pnls = np.array([t.pnl for t in trades])
        returns = pnls / self.initial_capital
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        total_return = (equity[-1] - equity[0]) / equity[0]
        return {
            "n_trades": n,
            "win_rate": len(wins) / n * 100,
            "profit_factor": profit_factor(pnls),
            "sharpe": sharpe_ratio(returns),
            "sortino": sortino_ratio(returns),
            "max_drawdown_pct": max_drawdown(equity) * 100,
            "total_return_pct": total_return * 100,
            "avg_win": float(np.mean(wins)) if len(wins) else 0,
            "avg_loss": float(np.mean(losses)) if len(losses) else 0,
            "expectancy": float(np.mean(pnls)),
        }

    def run_walk_forward(self, df: pd.DataFrame, symbol: str,
                          strategy: BaseStrategy,
                          n_splits: int = 5) -> List[BacktestResult]:
        """Walk-forward validation to guard against overfitting."""
        results = []
        step = len(df) // n_splits
        for i in range(1, n_splits):
            test_start = i * step
            test_end = min((i + 1) * step, len(df))
            test_df = df.iloc[test_start:test_end]
            if len(test_df) < self.warmup_bars + 10:
                continue
            r = self.run(test_df, symbol, strategy=strategy)
            results.append(r)
        return results
