"""Tests for the NSE-session-aware Opening Range Breakout fix
(docs/intraday_gaps.md §3): the opening range must anchor to today's
09:15 IST session open on real intraday data, and fall back to the
original bar-count window for data with no NSE-session clustering
(daily bars, continuous/crypto data)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.breakout.range_breakout import RangeBreakoutStrategy

CFG = {"range_minutes": 15, "range_bars": 8}


def _nse_session_df(breakout_direction: str | None = None) -> pd.DataFrame:
    """One NSE session, 5-minute bars from 09:15 to 11:00 (naive IST,
    matching this project's test convention). First 15 minutes (3 bars)
    form the opening range at 100-101; later bars stay inside the range
    unless breakout_direction pushes the final bar through it."""
    idx = pd.date_range("2026-08-24 09:15", periods=21, freq="5min")
    close = np.full(21, 100.5)
    high = np.full(21, 101.0)
    low = np.full(21, 100.0)

    if breakout_direction == "up":
        close[-1] = 110.0
        high[-1] = 110.5
    elif breakout_direction == "down":
        close[-1] = 90.0
        low[-1] = 89.5

    return pd.DataFrame({
        "open": close, "high": high, "low": low, "close": close,
        "volume": np.full(21, 5000.0),
    }, index=idx)


def test_session_range_detected_for_nse_open_time():
    strat = RangeBreakoutStrategy(CFG)
    df = _nse_session_df()
    session = strat._session_range(df)
    assert session is not None
    session_high, session_low, post_range = session
    assert session_high == 101.0
    assert session_low == 100.0
    # post_range excludes the opening-range bars themselves
    assert len(post_range) == 21 - 3


def test_no_signal_when_price_stays_inside_opening_range():
    strat = RangeBreakoutStrategy(CFG)
    df = _nse_session_df()
    signal = strat.generate_signal(df, "RELIANCE")
    assert signal is None


def test_buy_signal_on_upside_breakout_of_session_range():
    strat = RangeBreakoutStrategy(CFG)
    df = _nse_session_df("up")
    signal = strat.generate_signal(df, "RELIANCE")
    assert signal is not None
    assert signal.signal_type.value == "buy"
    assert signal.metadata["session_high"] == 101.0


def test_sell_signal_on_downside_breakout_of_session_range():
    strat = RangeBreakoutStrategy(CFG)
    df = _nse_session_df("down")
    signal = strat.generate_signal(df, "RELIANCE")
    assert signal is not None
    assert signal.signal_type.value == "sell"
    assert signal.metadata["session_low"] == 100.0


def test_falls_back_to_bar_count_window_for_daily_bar_data():
    # One row per calendar day — no intraday session to anchor to.
    strat = RangeBreakoutStrategy(CFG)
    idx = pd.date_range("2026-01-01", periods=20, freq="D")
    close = np.linspace(100, 120, 20)
    df = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": np.full(20, 1_000_000.0),
    }, index=idx)
    assert strat._session_range(df) is None
    # generate_signal should not raise and should use the legacy path
    strat.generate_signal(df, "RELIANCE")  # no assertion on outcome — just must not crash


def test_falls_back_for_data_with_no_datetime_index():
    strat = RangeBreakoutStrategy(CFG)
    df = pd.DataFrame({
        "open": np.full(20, 100.0), "high": np.full(20, 101.0),
        "low": np.full(20, 99.0), "close": np.full(20, 100.0),
        "volume": np.full(20, 1000.0),
    })  # default RangeIndex
    assert strat._session_range(df) is None


def test_falls_back_for_non_nse_open_time_e_g_crypto_hourly():
    # 24/7-style hourly bars starting at an arbitrary time, not clustered
    # near 09:15 IST — must not be mistaken for an NSE session.
    strat = RangeBreakoutStrategy(CFG)
    idx = pd.date_range("2026-08-24 00:00", periods=24, freq="1h")
    close = np.full(24, 50000.0)
    df = pd.DataFrame({
        "open": close, "high": close + 100, "low": close - 100, "close": close,
        "volume": np.full(24, 10.0),
    }, index=idx)
    assert strat._session_range(df) is None


def test_tz_aware_utc_timestamps_convert_correctly_to_ist_session():
    # Real Upstox data is tz-aware UTC. 09:15 IST == 03:45 UTC.
    strat = RangeBreakoutStrategy(CFG)
    idx = pd.date_range("2026-08-24 03:45", periods=21, freq="5min", tz="UTC")
    close = np.full(21, 100.5)
    df = pd.DataFrame({
        "open": close, "high": np.full(21, 101.0), "low": np.full(21, 100.0),
        "close": close, "volume": np.full(21, 5000.0),
    }, index=idx)
    session = strat._session_range(df)
    assert session is not None
    assert session[0] == 101.0
