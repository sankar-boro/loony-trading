"""Integration-level test for UpstoxTradingBot._refresh_live_df (the
docs/intraday_gaps.md §1 fix's wiring into main.py). Exercises the real,
unbound method against a lightweight stand-in exposing only the
attributes it touches — constructing a full UpstoxTradingBot needs live
Upstox credentials and heavy strategy/ML imports, which this test
deliberately avoids since the logic under test doesn't depend on any of
that."""
from __future__ import annotations
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from main import UpstoxTradingBot
from data_engine.live_bars import LiveBarAggregator


def _ts_ms(hour: int, minute: int, second: int = 0) -> int:
    dt = datetime(2026, 8, 24, hour, minute, second, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _event(symbol: str, hour: int, minute: int, second: int, close: float) -> dict:
    return {"symbol": symbol, "ts": _ts_ms(hour, minute, second),
            "open": close, "high": close, "low": close, "close": close, "volume": 100}


def _fake_bot(intraday_tf: str = "5m") -> SimpleNamespace:
    return SimpleNamespace(
        intraday_tf=intraday_tf,
        _live_bars=LiveBarAggregator(),
        _df_cache_base={},
        _df_cache={},
    )


def test_refresh_live_df_uses_live_bars_when_no_base_exists():
    bot = _fake_bot("1m")
    agg = bot._live_bars
    agg.update(_event("RELIANCE", 9, 15, 1, 100.0))
    agg.update(_event("RELIANCE", 9, 16, 1, 101.0))  # finalizes 09:15

    UpstoxTradingBot._refresh_live_df(bot, "RELIANCE")

    key = "RELIANCE_1m"
    assert key in bot._df_cache
    assert len(bot._df_cache[key]) == 1
    assert bot._df_cache[key].iloc[0]["close"] == 100.0


def test_refresh_live_df_merges_onto_historical_base():
    bot = _fake_bot("1m")
    key = "RELIANCE_1m"
    historical = pd.DataFrame(
        {"open": [90.0], "high": [91.0], "low": [89.0], "close": [90.5], "volume": [500]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-08-20 09:15", tz="UTC")], name="ts"),
    )
    bot._df_cache_base[key] = historical
    bot._df_cache[key] = historical

    agg = bot._live_bars
    agg.update(_event("RELIANCE", 9, 15, 1, 100.0))
    agg.update(_event("RELIANCE", 9, 16, 1, 101.0))  # finalizes today's 09:15 bar

    UpstoxTradingBot._refresh_live_df(bot, "RELIANCE")

    merged = bot._df_cache[key]
    assert len(merged) == 2  # yesterday's historical row + today's fresh live bar
    assert merged.iloc[0]["close"] == 90.5    # untouched historical row
    assert merged.iloc[-1]["close"] == 100.0  # fresh live bar, not stale


def test_refresh_live_df_is_a_noop_before_any_bar_finalizes():
    bot = _fake_bot("1m")
    key = "RELIANCE_1m"
    historical = pd.DataFrame(
        {"open": [90.0], "high": [91.0], "low": [89.0], "close": [90.5], "volume": [500]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-08-20 09:15", tz="UTC")], name="ts"),
    )
    bot._df_cache_base[key] = historical
    bot._df_cache[key] = historical

    # A tick within the still-forming minute — update() returns False.
    bot._live_bars.update(_event("RELIANCE", 9, 15, 1, 100.0))

    UpstoxTradingBot._refresh_live_df(bot, "RELIANCE")

    # Nothing finalized yet, so the merge should leave the base untouched.
    assert len(bot._df_cache[key]) == 1
    assert bot._df_cache[key].iloc[0]["close"] == 90.5
