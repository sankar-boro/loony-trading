import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest
from backtester import Backtester
from strategies.trend.ema_crossover import EmaCrossoverStrategy


def make_df(n: int = 500) -> pd.DataFrame:
    np.random.seed(0)
    price = 40000 + np.cumsum(np.random.normal(5, 300, n))
    return pd.DataFrame({
        "open": price,
        "high": price + np.abs(np.random.normal(0, 200, n)),
        "low": price - np.abs(np.random.normal(0, 200, n)),
        "close": price + np.random.normal(0, 100, n),
        "volume": np.abs(np.random.normal(1000, 300, n)),
    })


CFG = {
    "risk": {"max_risk_per_trade": 0.01},
    "execution": {"slippage_pct": 0.001, "commission": 0.001},
    "data": {"warmup_bars": 50},
}


def test_backtest_returns_result():
    df = make_df()
    bt = Backtester(CFG, initial_capital=10_000)
    strategy = EmaCrossoverStrategy({})
    result = bt.run(df, "BTC/USDT", strategy=strategy)
    assert result is not None
    assert isinstance(result.trades, list)
    assert len(result.equity_curve) > 0


def test_backtest_equity_starts_at_capital():
    df = make_df()
    bt = Backtester(CFG, initial_capital=10_000)
    strategy = EmaCrossoverStrategy({})
    result = bt.run(df, "BTC/USDT", strategy=strategy)
    assert result.equity_curve[0] == 10_000


def test_backtest_metrics_present():
    df = make_df()
    bt = Backtester(CFG, initial_capital=10_000)
    strategy = EmaCrossoverStrategy({})
    result = bt.run(df, "BTC/USDT", strategy=strategy)
    assert "n_trades" in result.metrics
    if result.metrics["n_trades"] > 0:
        assert "sharpe" in result.metrics
        assert "win_rate" in result.metrics


def test_walk_forward_returns_list():
    df = make_df(1000)
    bt = Backtester(CFG, initial_capital=10_000)
    strategy = EmaCrossoverStrategy({})
    results = bt.run_walk_forward(df, "BTC/USDT", strategy=strategy, n_splits=3)
    assert isinstance(results, list)
    assert len(results) >= 1
