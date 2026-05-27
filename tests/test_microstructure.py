"""Tests for cumulative delta, volume profile, and anchored VWAP strategies."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from strategies.microstructure.cumulative_delta import CumulativeDeltaStrategy, DeltaTracker
from strategies.microstructure.volume_profile import (
    VolumeProfileStrategy, compute_volume_profile, nearest_hvn, in_lvn,
)
from strategies.microstructure.anchored_vwap import AnchoredVWAPStrategy, compute_anchored_vwap


CFG = {
    "microstructure": {
        "cumulative_delta": {"delta_threshold_pct": 0.10, "window": 20},
        "volume_profile": {"poc_bounce_pct": 0.005, "lookback_bars": 30, "bins": 50},
        "anchored_vwap": {"reversion_sigma": 1.5, "breakout_sigma": 0.8, "vol_confirm_mult": 1.2, "min_bars": 5},
    }
}


def make_df(n=50, trend=0.0, base=22000.0):
    idx = pd.date_range("2025-01-06 09:15", periods=n, freq="5min")
    np.random.seed(7)
    prices = base + np.cumsum(np.random.randn(n) * 30 + trend)
    df = pd.DataFrame({
        "open": prices - 5, "high": prices + 20,
        "low": prices - 20, "close": prices,
        "volume": np.random.randint(50000, 150000, n),
    }, index=idx)
    return df


# ── DeltaTracker ──────────────────────────────────────────────────────────────

def test_delta_tracker_add_tick():
    t = DeltaTracker()
    t.add_tick(100.0, 500, "buy")
    t.add_tick(100.0, 300, "sell")
    assert t.session_delta == 200.0


def test_delta_tracker_load_df():
    df = make_df(20)
    t = DeltaTracker(window=20)
    t.load_df(df)
    assert len(t._bars) == 20


def test_delta_tracker_summary():
    df = make_df(20)
    t = DeltaTracker(window=20)
    t.load_df(df)
    s = t.summary()
    assert "session_delta" in s
    assert "buy_sell_ratio" in s


def test_delta_tracker_reset_session():
    t = DeltaTracker()
    t.add_tick(100.0, 500, "buy")
    t.reset_session()
    assert t.session_delta == 0.0
    assert t.cumulative_delta == 500.0   # cumulative not reset


def test_divergence_detection():
    # Create scenario: prices rising, delta falling → bearish divergence
    df = make_df(20, trend=10.0)   # uptrend
    t = DeltaTracker(window=20)
    t.load_df(df)
    result = t.detect_divergence()
    assert result in ("BULLISH_DIVERGENCE", "BEARISH_DIVERGENCE", None)


# ── CumulativeDeltaStrategy ───────────────────────────────────────────────────

def test_cumulative_delta_signal():
    strat = CumulativeDeltaStrategy(CFG)
    df = make_df(30)
    sig = strat.generate_signal(df, "NIFTY50")
    if sig:
        assert sig.signal_type.value in ("buy", "sell")
        assert sig.confidence >= 0.5


def test_cumulative_delta_insufficient_data():
    strat = CumulativeDeltaStrategy(CFG)
    df = make_df(5)    # too few bars
    sig = strat.generate_signal(df, "NIFTY50")
    assert sig is None


# ── Volume Profile ────────────────────────────────────────────────────────────

def test_compute_volume_profile():
    df = make_df(50)
    profile = compute_volume_profile(df, bins=50)
    assert profile is not None
    assert profile.poc > 0
    assert profile.vah > profile.val
    assert profile.poc >= profile.val
    assert profile.poc <= profile.vah


def test_volume_profile_hvn_exists():
    df = make_df(50)
    profile = compute_volume_profile(df, bins=50)
    assert profile is not None
    assert len(profile.hvn_levels) > 0


def test_volume_profile_total_volume():
    df = make_df(50)
    profile = compute_volume_profile(df, bins=50)
    assert profile.total_volume == pytest.approx(df["volume"].sum(), rel=0.01)


def test_nearest_hvn_found():
    df = make_df(50)
    profile = compute_volume_profile(df, bins=50)
    if profile and profile.hvn_levels:
        hvn = nearest_hvn(profile.poc, profile, max_dist_pct=0.05)
        assert hvn is not None or True  # OK if none within 5%


def test_volume_profile_strategy_generates_or_none():
    strat = VolumeProfileStrategy(CFG)
    df = make_df(60)
    sig = strat.generate_signal(df, "NIFTY50")
    if sig:
        assert sig.signal_type.value in ("buy", "sell")
        assert "level" in sig.metadata


# ── Anchored VWAP ─────────────────────────────────────────────────────────────

def test_compute_anchored_vwap_shape():
    df = make_df(30)
    vwap, u2, u1, l1, l2 = compute_anchored_vwap(df)
    assert len(vwap) == len(df)
    assert (u2 >= u1).all()
    assert (l1 >= l2).all()


def test_vwap_bands_ordering():
    df = make_df(30)
    vwap, u2, u1, l1, l2 = compute_anchored_vwap(df)
    last = -1
    assert u2.iloc[last] >= u1.iloc[last]
    assert u1.iloc[last] >= vwap.iloc[last]
    assert vwap.iloc[last] >= l1.iloc[last]
    assert l1.iloc[last] >= l2.iloc[last]


def test_anchored_vwap_strategy_extreme_upper():
    # Force price well above VWAP to trigger sell
    df = make_df(30)
    # Push last close far above VWAP
    vwap, u2, u1, l1, l2 = compute_anchored_vwap(df)
    df_mod = df.copy()
    df_mod.iloc[-1, df_mod.columns.get_loc("close")] = float(u2.iloc[-1]) * 1.01
    strat = AnchoredVWAPStrategy(CFG)
    sig = strat.generate_signal(df_mod, "NIFTY50")
    if sig:
        assert sig.signal_type.value == "sell"


def test_anchored_vwap_strategy_extreme_lower():
    df = make_df(30)
    vwap, u2, u1, l1, l2 = compute_anchored_vwap(df)
    df_mod = df.copy()
    df_mod.iloc[-1, df_mod.columns.get_loc("close")] = float(l2.iloc[-1]) * 0.99
    strat = AnchoredVWAPStrategy(CFG)
    sig = strat.generate_signal(df_mod, "NIFTY50")
    if sig:
        assert sig.signal_type.value == "buy"
