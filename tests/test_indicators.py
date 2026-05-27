import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest
from feature_engine.indicators import TechnicalIndicators as TI


def make_df(n: int = 200) -> pd.DataFrame:
    np.random.seed(42)
    price = 40000 + np.cumsum(np.random.normal(0, 200, n))
    return pd.DataFrame({
        "open": price,
        "high": price + np.abs(np.random.normal(0, 150, n)),
        "low": price - np.abs(np.random.normal(0, 150, n)),
        "close": price + np.random.normal(0, 50, n),
        "volume": np.abs(np.random.normal(1000, 300, n)),
    })


def test_ema_length():
    df = make_df()
    result = TI.ema(df["close"], 20)
    assert len(result) == len(df)


def test_rsi_bounds():
    df = make_df()
    rsi = TI.rsi(df["close"], 14).dropna()
    assert (rsi >= 0).all() and (rsi <= 100).all()


def test_bollinger_bands_ordering():
    df = make_df()
    upper, mid, lower = TI.bollinger_bands(df["close"], 20, 2)
    valid = ~upper.isna()
    assert (upper[valid] >= mid[valid]).all()
    assert (mid[valid] >= lower[valid]).all()


def test_atr_positive():
    df = make_df()
    atr = TI.atr(df, 14).dropna()
    assert (atr > 0).all()


def test_adx_range():
    df = make_df()
    adx, _, _ = TI.adx(df, 14)
    valid = adx.dropna()
    assert (valid >= 0).all()


def test_supertrend_direction():
    df = make_df()
    _, direction = TI.supertrend(df)
    valid = direction.dropna()
    assert set(valid.unique()).issubset({1, -1})


def test_donchian_ordering():
    df = make_df()
    upper, mid, lower = TI.donchian_channel(df, 20)
    valid = ~upper.isna()
    assert (upper[valid] >= lower[valid]).all()
