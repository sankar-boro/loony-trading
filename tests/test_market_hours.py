import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
import zoneinfo
import pytest

from data_engine.upstox.market_hours import (
    is_market_open, is_pre_open, is_amo_window,
    minutes_to_close, next_market_open, IST,
)


def ist(hour, minute, weekday_offset=0):
    """Create a test datetime in IST with a given time on a weekday."""
    # Use 2025-01-06 (Monday) as base
    from datetime import timedelta
    base = datetime(2025, 1, 6, hour, minute, 0, tzinfo=IST)
    return base + timedelta(days=weekday_offset)


def test_market_open_during_session():
    dt = ist(10, 30)
    assert is_market_open(dt) is True


def test_market_open_at_open():
    dt = ist(9, 15)
    assert is_market_open(dt) is True


def test_market_open_at_close():
    dt = ist(15, 30)
    assert is_market_open(dt) is True


def test_market_closed_before_open():
    dt = ist(9, 0)
    assert is_market_open(dt) is False


def test_market_closed_after_close():
    dt = ist(15, 31)
    assert is_market_open(dt) is False


def test_market_closed_saturday():
    dt = ist(10, 30, weekday_offset=5)  # Saturday
    assert is_market_open(dt) is False


def test_market_closed_sunday():
    dt = ist(10, 30, weekday_offset=6)  # Sunday
    assert is_market_open(dt) is False


def test_pre_open_window():
    dt = ist(9, 5)
    assert is_pre_open(dt) is True


def test_not_pre_open_after_market_open():
    dt = ist(9, 20)
    assert is_pre_open(dt) is False


def test_amo_window_evening():
    dt = ist(18, 0)
    assert is_amo_window(dt) is True


def test_not_amo_during_market():
    dt = ist(11, 0)
    assert is_amo_window(dt) is False


def test_minutes_to_close_during_session():
    dt = ist(14, 30)
    mins = minutes_to_close(dt)
    assert mins == 60


def test_minutes_to_close_after_market():
    dt = ist(16, 0)
    assert minutes_to_close(dt) == 0


def test_next_market_open_is_future():
    nxt = next_market_open()
    assert nxt is not None
    assert nxt.tzinfo is not None


def test_next_market_open_is_weekday():
    nxt = next_market_open()
    assert nxt.weekday() < 5
