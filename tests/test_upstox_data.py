"""
Tests for UpstoxDataEngine — exercises caching and data normalisation
using mocked HTTP responses (no real API calls).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from data_engine.upstox.auth import UpstoxAuth
from data_engine.upstox.instruments import InstrumentRegistry, KNOWN_INSTRUMENTS
from data_engine.upstox.upstox_data import UpstoxDataEngine, _TF_MAP


# ── Fixtures ───────────────────────────────────────────────────────────────────

def make_auth():
    auth = MagicMock(spec=UpstoxAuth)
    auth.access_token = "test_token"
    auth.auth_header = {"Authorization": "Bearer test_token", "Accept": "application/json"}
    return auth


def make_registry():
    reg = InstrumentRegistry()
    for sym, key in KNOWN_INSTRUMENTS.items():
        reg._by_symbol[sym] = {"instrument_key": key, "tradingsymbol": sym,
                                "exchange": key.split("|")[0],
                                "lot_size": "1", "tick_size": "0.05"}
    reg._loaded = True
    return reg


def make_candle_response(n: int = 10, base: float = 2900.0) -> dict:
    """Build a fake Upstox historical-candle API response."""
    from datetime import timedelta
    candles = []
    start = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    price = base
    for i in range(n):
        ts = (start + timedelta(days=i)).isoformat()
        price += np.random.normal(5, 30)
        candles.append([ts, price, price + 20, price - 20, price + 5, 100_000, 0])
    return {"data": {"candles": candles}}


@pytest.fixture
def engine(tmp_path):
    auth = make_auth()
    reg  = make_registry()
    eng  = UpstoxDataEngine(auth, reg, cache_dir=str(tmp_path))
    return eng


# ── Timeframe mapping tests ────────────────────────────────────────────────────

def test_tf_map_daily():
    assert _TF_MAP["1d"] == "day"

def test_tf_map_15m():
    assert _TF_MAP["15m"] == "15minute"

def test_tf_map_1h():
    assert _TF_MAP["1h"] == "30minute"

def test_tf_map_week():
    assert _TF_MAP["1w"] == "week"


# ── Chunk fetch and DataFrame normalisation ────────────────────────────────────

def test_fetch_chunk_returns_dataframe(engine):
    mock_resp = make_candle_response(n=20)
    with patch.object(engine, "_get", return_value=mock_resp):
        from datetime import datetime, timedelta, timezone
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end   = datetime(2025, 1, 31, tzinfo=timezone.utc)
        df = engine._fetch_chunk("NSE_EQ|INE002A01018", "day", start, end)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 20
    assert set(df.columns) == {"open", "high", "low", "close", "volume"}


def test_fetch_chunk_empty_response(engine):
    with patch.object(engine, "_get", return_value={"data": {"candles": []}}):
        from datetime import datetime, timezone
        df = engine._fetch_chunk("NSE_EQ|INE002A01018", "day",
                                  datetime(2025, 1, 1, tzinfo=timezone.utc),
                                  datetime(2025, 1, 31, tzinfo=timezone.utc))
    assert df.empty


def test_fetch_chunk_error_returns_empty(engine):
    with patch.object(engine, "_get", side_effect=Exception("timeout")):
        from datetime import datetime, timezone
        df = engine._fetch_chunk("NSE_EQ|INE002A01018", "day",
                                  datetime(2025, 1, 1, tzinfo=timezone.utc),
                                  datetime(2025, 1, 31, tzinfo=timezone.utc))
    assert df.empty


def test_ohlcv_high_ge_low(engine):
    mock_resp = make_candle_response(n=30)
    with patch.object(engine, "_get", return_value=mock_resp):
        from datetime import datetime, timezone
        df = engine._fetch_chunk("NSE_EQ|INE002A01018", "day",
                                  datetime(2025, 1, 1, tzinfo=timezone.utc),
                                  datetime(2025, 2, 1, tzinfo=timezone.utc))
    assert (df["high"] >= df["low"]).all()


# ── Resample 1h ────────────────────────────────────────────────────────────────

def test_resample_to_1h():
    idx = pd.date_range("2025-01-01 09:00", periods=12, freq="30min", tz="UTC")
    df30 = pd.DataFrame({
        "open":   np.ones(12) * 100,
        "high":   np.ones(12) * 110,
        "low":    np.ones(12) * 90,
        "close":  np.ones(12) * 105,
        "volume": np.ones(12) * 1000,
    }, index=idx)
    df1h = UpstoxDataEngine._resample_to_1h(df30)
    assert len(df1h) == 6
    assert (df1h["high"] >= df1h["low"]).all()


# ── Cache ──────────────────────────────────────────────────────────────────────

def test_fetch_ohlcv_caches_result(engine, tmp_path):
    mock_resp = make_candle_response(n=50)
    with patch.object(engine, "_get", return_value=mock_resp):
        df1 = engine.fetch_ohlcv("RELIANCE", "1d", lookback_days=90)
    assert df1 is not None and not df1.empty
    # Second call should return from in-memory cache (no _get call needed)
    df2 = engine.get_cached("RELIANCE", "1d")
    assert df2 is not None
    assert len(df2) == len(df1)


# ── LTP / Quotes ──────────────────────────────────────────────────────────────

def test_get_ltp_returns_dict(engine):
    mock_resp = {"data": {"NSE_EQ|INE002A01018": {"last_price": 2912.5}}}
    with patch.object(engine, "_get", return_value=mock_resp):
        result = engine.get_ltp(["RELIANCE"])
    assert isinstance(result, dict)


def test_get_ltp_error_returns_empty(engine):
    with patch.object(engine, "_get", side_effect=Exception("err")):
        result = engine.get_ltp(["RELIANCE"])
    assert result == {}


def test_get_quotes_structure(engine):
    mock_resp = {
        "data": {
            "NSE_EQ|INE002A01018": {
                "last_price": 2912.0,
                "ohlc": {"open": 2890.0, "high": 2930.0, "low": 2875.0, "close": 2905.0},
                "volume": 500_000,
                "net_change": 0.82,
            }
        }
    }
    with patch.object(engine, "_get", return_value=mock_resp):
        result = engine.get_quotes(["RELIANCE"])
    assert isinstance(result, dict)


# ── Resolve key ────────────────────────────────────────────────────────────────

def test_resolve_key_symbol(engine):
    key = engine._resolve_key("RELIANCE")
    assert key == "NSE_EQ|INE002A01018"


def test_resolve_key_passthrough(engine):
    key = engine._resolve_key("NSE_EQ|INE002A01018")
    assert key == "NSE_EQ|INE002A01018"


def test_resolve_key_unknown(engine):
    key = engine._resolve_key("UNKNOWNSYM999")
    assert key is None
