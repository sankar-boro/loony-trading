"""Tests for the session-boundary VWAP fix (docs/intraday_gaps.md §3):
TechnicalIndicators.vwap()/vwap_bands() and
strategies.microstructure.anchored_vwap.compute_anchored_vwap() must
reset at each trading day, not run cumulatively across multiple days of
intraday bars."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_engine.indicators import TechnicalIndicators as TI
from strategies.microstructure.anchored_vwap import compute_anchored_vwap


def _two_day_intraday_df(bars_per_day: int = 6) -> pd.DataFrame:
    """Two NSE sessions of 5-minute bars, flat volume/price within each
    day but a different level on day 2 — chosen so a bug (VWAP blending
    across days) is easy to detect: correct behaviour means day 2's VWAP
    matches day 2's own prices, not a blend with day 1's."""
    day1 = pd.date_range("2026-08-20 09:15", periods=bars_per_day, freq="5min", tz="UTC")
    day2 = pd.date_range("2026-08-21 09:15", periods=bars_per_day, freq="5min", tz="UTC")
    idx = day1.append(day2)

    day1_price, day2_price = 100.0, 500.0  # deliberately far apart
    close = np.array([day1_price] * bars_per_day + [day2_price] * bars_per_day)
    df = pd.DataFrame({
        "open": close, "high": close, "low": close, "close": close,
        "volume": np.full(len(idx), 1000.0),
    }, index=idx)
    return df


def test_session_cumsum_resets_across_days_with_datetime_index():
    df = _two_day_intraday_df()
    result = TI.session_cumsum(df["volume"], df.index)
    # Day 2's cumulative volume must restart from its own first bar, not
    # continue accumulating from day 1.
    day2_first = result.iloc[6]
    assert day2_first == 1000.0


def test_session_cumsum_falls_back_to_plain_cumsum_without_datetime_index():
    series = pd.Series([1.0, 2.0, 3.0])
    result = TI.session_cumsum(series, series.index)
    assert list(result) == [1.0, 3.0, 6.0]  # unchanged prior behaviour


def test_vwap_does_not_blend_across_session_boundary():
    df = _two_day_intraday_df()
    vwap = TI.vwap(df)
    # Day 1 is flat at 100 -> VWAP should equal 100 throughout day 1.
    assert vwap.iloc[:6].round(4).eq(100.0).all()
    # Day 2 is flat at 500 -> VWAP should equal 500 from day 2's first
    # bar, not a blend like ~114 (bug: 6*100 + 1*500 averaged in).
    assert vwap.iloc[6] == pytest.approx(500.0)
    assert vwap.iloc[6:].round(4).eq(500.0).all()


def test_vwap_single_session_matches_prior_cumulative_behaviour():
    # A single day's worth of bars — session-aware and plain cumsum must
    # agree exactly, since there's only one group.
    idx = pd.date_range("2026-08-20 09:15", periods=10, freq="5min", tz="UTC")
    np.random.seed(1)
    close = 100 + np.cumsum(np.random.randn(10))
    df = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": np.random.randint(100, 1000, 10).astype(float),
    }, index=idx)

    tp = (df["high"] + df["low"] + df["close"]) / 3
    expected = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
    actual = TI.vwap(df)
    pd.testing.assert_series_equal(actual, expected, check_names=False)


def test_vwap_bands_ordering_holds_across_session_reset():
    df = _two_day_intraday_df()
    upper, vwap, lower = TI.vwap_bands(df)
    # Flat prices within each day -> zero variance -> bands collapse to vwap.
    assert (upper.round(4) == vwap.round(4)).all()
    assert (lower.round(4) == vwap.round(4)).all()


def test_compute_anchored_vwap_does_not_blend_across_session_boundary():
    df = _two_day_intraday_df()
    vwap, upper2, upper1, lower1, lower2 = compute_anchored_vwap(df)
    assert vwap.iloc[:6].round(4).eq(100.0).all()
    assert vwap.iloc[6:].round(4).eq(500.0).all()
    # No bug-induced blended value anywhere near the boundary.
    assert vwap.iloc[6] == pytest.approx(500.0)


def test_compute_anchored_vwap_with_real_volatility_still_resets():
    """A less contrived case: varying prices/volume within each day,
    still must not let day 2 inherit any of day 1's accumulation."""
    day1 = pd.date_range("2026-08-20 09:15", periods=20, freq="5min", tz="UTC")
    day2 = pd.date_range("2026-08-21 09:15", periods=20, freq="5min", tz="UTC")
    idx = day1.append(day2)

    rng = np.random.RandomState(42)
    day1_close = 100 + np.cumsum(rng.randn(20))
    day2_close = 1000 + np.cumsum(rng.randn(20))  # very different price regime
    close = np.concatenate([day1_close, day2_close])
    volume = rng.randint(100, 5000, 40).astype(float)

    df = pd.DataFrame({
        "open": close, "high": close + rng.rand(40), "low": close - rng.rand(40),
        "close": close, "volume": volume,
    }, index=idx)

    vwap, *_ = compute_anchored_vwap(df)
    # Day 2's VWAP must stay within day 2's own price range, not be
    # dragged toward day 1's ~100 level by leftover cumulative volume.
    day2_vwap = vwap.iloc[20:]
    assert day2_vwap.min() > 500  # nowhere close to day 1's price level
