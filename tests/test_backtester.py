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


def test_median_trade_return_and_avg_holding_bars():
    from backtester.backtester import Trade

    bt = Backtester(CFG, initial_capital=10_000)
    trades = [
        # +5% over 10 bars, long
        Trade(symbol="X", direction=1, entry_price=100, exit_price=105, size=1,
              entry_bar=0, exit_bar=10, pnl=5, strategy="s", reason="take_profit"),
        # -2% over 4 bars, long
        Trade(symbol="X", direction=1, entry_price=100, exit_price=98, size=1,
              entry_bar=10, exit_bar=14, pnl=-2, strategy="s", reason="stop_loss"),
        # +20% over 30 bars, long — median should be the middle value (5%), not skewed by this
        Trade(symbol="X", direction=1, entry_price=100, exit_price=120, size=1,
              entry_bar=14, exit_bar=44, pnl=20, strategy="s", reason="take_profit"),
    ]
    equity = np.array([10_000, 10_005, 10_003, 10_023])
    metrics = bt._compute_metrics(trades, equity)

    assert metrics["median_trade_return_pct"] == pytest.approx(5.0)
    assert metrics["avg_holding_bars"] == pytest.approx((10 + 4 + 30) / 3)


def test_empty_trades_metrics_include_new_fields():
    bt = Backtester(CFG, initial_capital=10_000)
    metrics = bt._compute_metrics([], np.array([10_000.0]))
    assert metrics["median_trade_return_pct"] == 0.0
    assert metrics["avg_holding_bars"] == 0.0
