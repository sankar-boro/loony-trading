"""Upstox daily tokens expire at 03:30 IST, not a fixed number of hours
after issue (docs/appendix/status.md §4)."""
from __future__ import annotations
from datetime import datetime

from data_engine.upstox.auth import UpstoxAuth, token_expires_at, token_hours_left
from utils.timeutils import IST


def _ts(y, mo, d, h, mi) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=IST).timestamp()


def test_daytime_token_expires_next_morning():
    assert token_expires_at(_ts(2026, 10, 9, 9, 0)) == _ts(2026, 10, 10, 3, 30)


def test_early_morning_token_expires_same_morning():
    assert token_expires_at(_ts(2026, 10, 9, 2, 0)) == _ts(2026, 10, 9, 3, 30)


def test_token_issued_at_0330_lasts_until_next_day():
    assert token_expires_at(_ts(2026, 10, 9, 3, 30)) == _ts(2026, 10, 10, 3, 30)


def test_token_dead_after_0330_even_if_under_23h_old():
    issued = _ts(2026, 10, 9, 9, 0)
    # 20 hours later is 05:00 IST next day: under the old 23h rule this looked valid
    assert token_hours_left(issued, now=issued + 20 * 3600) < 0
    assert token_hours_left(issued, now=issued + 18 * 3600) > 0   # 03:00 IST


def test_is_valid_uses_real_expiry(monkeypatch):
    auth = UpstoxAuth.__new__(UpstoxAuth)
    issued = _ts(2026, 10, 9, 9, 0)
    auth._token_data = {"access_token": "x", "obtained_at": issued}
    monkeypatch.setattr("data_engine.upstox.auth.time.time", lambda: issued + 20 * 3600)
    assert auth.is_valid() is False
