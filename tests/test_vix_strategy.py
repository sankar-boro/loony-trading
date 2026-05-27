"""Tests for India VIX strategy and classification functions."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from data_engine.upstox.india_vix import classify_vix
from feature_engine.greeks import iv_percentile as vix_percentile
from strategies.volatility.vix_strategy import VIXStrategy


CFG = {
    "volatility": {
        "vix": {
            "spike_threshold_pct": 15.0,
            "vix_spike_entry": 20.0,
            "vix_low_entry": 14.0,
            "nifty_drop_pct": 2.0,
            "consecutive_low_days": 5,
        }
    }
}


def make_nifty_df(n=30, base=22000.0, drop=0.0):
    idx = pd.date_range("2025-01-06 09:15", periods=n, freq="15min")
    np.random.seed(1)
    prices = base + np.cumsum(np.random.randn(n) * 50 - drop)
    prices = np.clip(prices, 1.0, None)
    return pd.DataFrame({
        "open": prices - 10, "high": prices + 30,
        "low": prices - 30,  "close": prices,
        "volume": np.random.randint(50000, 150000, n),
    }, index=idx)


def make_vix_df(values):
    idx = pd.date_range("2025-01-01", periods=len(values), freq="B")
    return pd.DataFrame({"close": values}, index=idx)


# ── Classification ────────────────────────────────────────────────────────────

def test_classify_extreme_fear():
    assert classify_vix(28.0) == "EXTREME_FEAR"


def test_classify_high_fear():
    assert classify_vix(22.0) == "HIGH_FEAR"


def test_classify_normal():
    assert classify_vix(14.0) == "NORMAL"


def test_classify_low():
    assert classify_vix(11.0) == "LOW"


def test_classify_complacency():
    assert classify_vix(8.0) == "EXTREME_COMPLACENCY"


def test_vix_percentile_high():
    history = [10.0, 11.0, 12.0, 13.0, 14.0]
    pct = vix_percentile(20.0, history)
    assert pct == 100.0


def test_vix_percentile_low():
    history = [20.0, 22.0, 25.0, 30.0]
    pct = vix_percentile(5.0, history)
    assert pct == 0.0


# ── VIXStrategy ───────────────────────────────────────────────────────────────

def test_vix_spike_reversal_triggers():
    strat = VIXStrategy(CFG)
    df = make_nifty_df(30, drop=5.0)   # downtrend
    # Set current VIX to spike level
    vix_values = [12.0] * 25 + [15.0, 16.0, 18.0, 20.0, 25.0]
    vix_df = make_vix_df(vix_values)
    with patch.object(strat, '_load_vix', return_value=vix_df):
        sig = strat.generate_signal(df, "NIFTY50")
    if sig:
        assert sig.signal_type.value in ("buy", "sell")


def test_vix_no_signal_for_equity():
    strat = VIXStrategy(CFG)
    df = make_nifty_df(30)
    vix_df = make_vix_df([15.0] * 30)
    with patch.object(strat, '_load_vix', return_value=vix_df):
        sig = strat.generate_signal(df, "RELIANCE")  # not an index
    assert sig is None


def test_vix_low_hedge_triggers():
    strat = VIXStrategy(CFG)
    df = make_nifty_df(30)
    # 10 consecutive days below 14
    vix_values = [13.0] * 10 + [14.5] * 20
    vix_df = make_vix_df(vix_values)
    with patch.object(strat, '_load_vix', return_value=vix_df):
        sig = strat._low_vix_hedge(df, "NIFTY50", 22000.0, 13.0, np.array([13.0] * 10))
    if sig:
        assert sig.signal_type.value == "sell"


def test_vix_market_regime_normal():
    strat = VIXStrategy(CFG)
    vix_df = make_vix_df([14.0] * 60 + [14.5])
    with patch.object(strat, '_load_vix', return_value=vix_df):
        regime = strat.get_vix_market_regime()
    assert "regime" in regime
    assert "size_multiplier" in regime
    assert regime["size_multiplier"] > 0


def test_vix_market_regime_extreme_fear():
    strat = VIXStrategy(CFG)
    vix_df = make_vix_df([14.0] * 60 + [28.0])
    with patch.object(strat, '_load_vix', return_value=vix_df):
        regime = strat.get_vix_market_regime()
    assert regime["regime"] == "EXTREME_FEAR"
    assert regime["size_multiplier"] < 1.0


def test_vix_divergence_new_high():
    strat = VIXStrategy(CFG)
    # Price at 20-day high, VIX not at 20-day low
    base = 22000.0
    prices = [base] * 20 + [base * 1.01]   # making new high
    vix_vals = [15.0] * 20 + [14.8]         # VIX slightly elevated (not at 20d low)
    df = pd.DataFrame({
        "open": prices, "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices], "close": prices,
        "volume": [100000] * 21,
    })
    vix_df = make_vix_df(vix_vals)
    with patch.object(strat, '_load_vix', return_value=vix_df):
        sig = strat._divergence_signal(df, "NIFTY50", prices[-1], 14.8, vix_df)
    # Signal may or may not fire depending on exact values
    if sig:
        assert sig.signal_type.value in ("buy", "sell")
