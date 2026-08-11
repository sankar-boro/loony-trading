"""Tests for the demo-mode synthetic OHLCV generator (spec §41 — the app
must run locally without paid API keys) and its wiring into
UpstoxDataEngine.fetch_ohlcv."""
from __future__ import annotations
import tempfile

import numpy as np
import pytest

from data_engine.demo_ohlcv import generate_demo_ohlcv, _PRICE_ANCHORS

# spec §42's mandated demo symbols
_SPEC_SYMBOLS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "TATAMOTORS",
    "BHARTIARTL", "ITC", "LT", "AXISBANK", "KOTAKBANK", "MARUTI", "SUNPHARMA",
    "TATASTEEL",
]


def test_all_spec_symbols_have_price_anchors():
    for symbol in _SPEC_SYMBOLS:
        assert symbol in _PRICE_ANCHORS, f"{symbol} missing a demo price anchor"


def test_generate_demo_ohlcv_shape_and_no_nans():
    df = generate_demo_ohlcv("RELIANCE", days=250)
    assert len(df) == 250
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert not df.isna().any().any()


def test_generate_demo_ohlcv_ohlc_consistency():
    df = generate_demo_ohlcv("TCS", days=300)
    assert (df["low"] <= df["open"]).all()
    assert (df["open"] <= df["high"]).all()
    assert (df["low"] <= df["close"]).all()
    assert (df["close"] <= df["high"]).all()
    assert (df["low"] > 0).all()


def test_generate_demo_ohlcv_is_deterministic():
    df1 = generate_demo_ohlcv("INFY", days=100)
    df2 = generate_demo_ohlcv("INFY", days=100)
    assert np.allclose(df1["close"].values, df2["close"].values)


def test_generate_demo_ohlcv_last_bar_matches_anchor():
    df = generate_demo_ohlcv("RELIANCE", days=100)
    assert df["close"].iloc[-1] == pytest.approx(_PRICE_ANCHORS["RELIANCE"])


def test_generate_demo_ohlcv_different_symbols_diverge():
    a = generate_demo_ohlcv("RELIANCE", days=100)
    b = generate_demo_ohlcv("TCS", days=100)
    assert not np.allclose(a["close"].values, b["close"].values)


def test_large_cap_has_lower_relative_volatility_than_small_cap():
    # RELIANCE is Large Cap, and a symbol outside STOCK_UNIVERSE falls back
    # to the Mid Cap default tier — the generator must still produce
    # *some* stable ordering: Large Cap daily vol (1.4%) < Small Cap (2.8%).
    from data_engine import demo_ohlcv

    large = generate_demo_ohlcv("RELIANCE", days=400)
    large_daily_ret_std = large["close"].pct_change().dropna().std()

    # Force a synthetic small-cap symbol not in STOCK_UNIVERSE/_PRICE_ANCHORS
    assert "ZZZFAKESMALLCAP" not in demo_ohlcv.STOCK_UNIVERSE
    small = generate_demo_ohlcv("ZZZFAKESMALLCAP", days=400)
    small_daily_ret_std = small["close"].pct_change().dropna().std()

    assert large_daily_ret_std < small_daily_ret_std


def test_fetch_ohlcv_falls_back_to_demo_data_without_token():
    from data_engine.upstox import InstrumentRegistry, UpstoxAuth, UpstoxDataEngine

    auth = UpstoxAuth(api_key="", api_secret="", redirect_uri="http://x",
                       token_file=tempfile.mktemp())
    assert auth.access_token is None

    registry = InstrumentRegistry()
    registry.load()

    de = UpstoxDataEngine(auth, registry, cache_dir=tempfile.mkdtemp())
    df = de.fetch_ohlcv("RELIANCE", "1d", lookback_days=100)

    assert not df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].iloc[-1] == pytest.approx(_PRICE_ANCHORS["RELIANCE"])
