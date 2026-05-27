import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest
from strategies.base import SignalType
from strategies.trend.ema_crossover import EmaCrossoverStrategy
from strategies.mean_reversion.rsi_reversion import RsiReversionStrategy
from strategies.mean_reversion.bollinger_reversion import BollingerReversionStrategy
from strategies.momentum.macd_momentum import MacdMomentumStrategy
from strategies.breakout.atr_breakout import AtrBreakoutStrategy


def make_df(n: int = 200, trend: float = 0.0) -> pd.DataFrame:
    np.random.seed(42)
    price = 40000 + np.cumsum(np.random.normal(trend, 200, n))
    high = price + np.abs(np.random.normal(0, 150, n))
    low = price - np.abs(np.random.normal(0, 150, n))
    return pd.DataFrame({
        "open": price,
        "high": high,
        "low": low,
        "close": price + np.random.normal(0, 50, n),
        "volume": np.abs(np.random.normal(1000, 300, n)),
    })


CFG = {}


def test_ema_crossover_returns_signal_or_none():
    df = make_df(trend=10)
    strategy = EmaCrossoverStrategy(CFG)
    result = strategy.generate_signal(df, "BTC/USDT")
    assert result is None or result.signal_type in (SignalType.BUY, SignalType.SELL)


def test_rsi_reversion_signal_has_valid_stops():
    df = make_df()
    strategy = RsiReversionStrategy(CFG)
    result = strategy.generate_signal(df, "BTC/USDT")
    if result is not None:
        assert result.stop_loss > 0
        assert result.take_profit > 0
        assert 0 <= result.confidence <= 1


def test_bollinger_signal_confidence_range():
    df = make_df()
    strategy = BollingerReversionStrategy(CFG)
    result = strategy.generate_signal(df, "BTC/USDT")
    if result is not None:
        assert 0 <= result.confidence <= 1


def test_macd_momentum_not_crash():
    df = make_df()
    strategy = MacdMomentumStrategy(CFG)
    result = strategy.generate_signal(df, "ETH/USDT")
    # just ensure it doesn't raise


def test_atr_breakout_not_crash():
    df = make_df()
    strategy = AtrBreakoutStrategy(CFG)
    result = strategy.generate_signal(df, "BTC/USDT")


def test_strategy_requires_min_bars():
    df = make_df(n=10)  # too short
    strategy = EmaCrossoverStrategy(CFG)
    result = strategy.generate_signal(df, "BTC/USDT")
    assert result is None
