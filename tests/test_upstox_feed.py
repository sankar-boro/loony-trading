"""
Tests for UpstoxFeed — protobuf decoding, varint parser,
event normalisation, and symbol resolution. No network calls.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import struct
import pytest
from unittest.mock import MagicMock

from data_engine.upstox.upstox_feed import UpstoxFeed, MarketEvent
from data_engine.upstox.auth import UpstoxAuth
from data_engine.upstox.instruments import KNOWN_INSTRUMENTS


def make_feed():
    auth = MagicMock(spec=UpstoxAuth)
    auth.access_token = "test"
    reg = MagicMock()
    reg.get_key.side_effect = lambda s: KNOWN_INSTRUMENTS.get(s.upper())
    reg.get_metadata.return_value = None
    return UpstoxFeed(auth, reg)


# ── MarketEvent ────────────────────────────────────────────────────────────────

def test_market_event_defaults():
    evt = MarketEvent("NSE_EQ|INE002A01018")
    assert evt.ltp == 0.0
    assert evt.instrument_key == "NSE_EQ|INE002A01018"


def test_market_event_to_candle_event():
    evt = MarketEvent("NSE_EQ|INE002A01018")
    evt.ltp = 2912.5
    evt.volume = 100_000
    candle = evt.to_candle_event()
    assert candle["close"] == 2912.5
    assert candle["volume"] == 100_000
    assert candle["timeframe"] == "tick"


# ── Varint parser ──────────────────────────────────────────────────────────────

def test_read_varint_single_byte():
    data = bytes([0x05])
    val, pos = UpstoxFeed._read_varint(data, 0)
    assert val == 5
    assert pos == 1


def test_read_varint_multibyte():
    # 300 encoded as varint: 0xAC 0x02
    data = bytes([0xAC, 0x02])
    val, pos = UpstoxFeed._read_varint(data, 0)
    assert val == 300
    assert pos == 2


def test_read_varint_zero():
    data = bytes([0x00])
    val, pos = UpstoxFeed._read_varint(data, 0)
    assert val == 0


# ── Symbol resolution ──────────────────────────────────────────────────────────

def test_resolve_keys_known_symbol():
    feed = make_feed()
    keys = feed._resolve_keys(["RELIANCE"])
    assert "NSE_EQ|INE002A01018" in keys


def test_resolve_keys_instrument_key_passthrough():
    feed = make_feed()
    keys = feed._resolve_keys(["NSE_EQ|INE002A01018"])
    assert "NSE_EQ|INE002A01018" in keys


def test_resolve_keys_unknown_skipped():
    feed = make_feed()
    keys = feed._resolve_keys(["GHOST999"])
    assert len(keys) == 0


def test_resolve_keys_mixed():
    feed = make_feed()
    keys = feed._resolve_keys(["RELIANCE", "NSE_EQ|INE040A01034"])
    assert len(keys) == 2


# ── Manual protobuf decode (sanity) ──────────────────────────────────────────

def test_decode_manual_empty_data():
    feed = make_feed()
    events = feed._decode_manual(b"")
    assert events == []


def test_decode_manual_garbage_data():
    feed = make_feed()
    # Should not raise — just return []
    events = feed._decode_manual(b"\xff\xfe\xfd\xab\xcd\xef")
    assert isinstance(events, list)


def test_get_ltp_initial():
    feed = make_feed()
    assert feed.get_ltp("RELIANCE") == 0.0


def test_get_ltp_after_update():
    feed = make_feed()
    feed._last_prices["RELIANCE"] = 2912.5
    assert feed.get_ltp("RELIANCE") == 2912.5


# ── Mode constant ──────────────────────────────────────────────────────────────

def test_feed_default_mode():
    feed = make_feed()
    assert feed.mode in ("ltpc", "full", "option")
