"""Tests for the intraday live bar aggregator (docs/appendix/intraday-audit.md §1/§7
fix, Phase 1). Uses synthetic MarketEvent-shaped payloads — no live
Upstox connection needed, since this module's job is pure aggregation
logic independent of the feed itself."""
from __future__ import annotations
from datetime import datetime, timezone

import pandas as pd
import pytest

from data_engine.live_bars import LiveBarAggregator, merge_live_onto_history, timeframe_minutes


def _ts_ms(hour: int, minute: int, second: int = 0) -> int:
    dt = datetime(2026, 8, 24, hour, minute, second, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _event(symbol: str, hour: int, minute: int, second: int, close: float,
           high: float | None = None, low: float | None = None, volume: float = 100) -> dict:
    return {
        "symbol": symbol, "timeframe": "tick", "ts": _ts_ms(hour, minute, second),
        "open": close, "high": high or close, "low": low or close,
        "close": close, "volume": volume,
    }


def test_timeframe_minutes_parses_common_strings():
    assert timeframe_minutes("1m") == 1
    assert timeframe_minutes("5m") == 5
    assert timeframe_minutes("15m") == 15
    assert timeframe_minutes("1h") == 60
    assert timeframe_minutes("unknown") == 1


def test_update_returns_false_within_same_minute():
    agg = LiveBarAggregator()
    assert agg.update(_event("RELIANCE", 9, 15, 1, 100.0)) is False
    assert agg.update(_event("RELIANCE", 9, 15, 30, 101.0)) is False
    assert agg.get_bars("RELIANCE", "1m").empty  # nothing finalized yet


def test_update_finalizes_bar_when_new_minute_starts():
    agg = LiveBarAggregator()
    agg.update(_event("RELIANCE", 9, 15, 1, 100.0))
    agg.update(_event("RELIANCE", 9, 15, 30, 101.0))
    finalized = agg.update(_event("RELIANCE", 9, 16, 1, 102.0))
    assert finalized is True

    bars = agg.get_bars("RELIANCE", "1m")
    assert len(bars) == 1
    row = bars.iloc[0]
    assert row["open"] == 100.0
    assert row["close"] == 101.0  # last tick within the 09:15 minute


def test_high_low_track_extremes_within_a_forming_bar():
    agg = LiveBarAggregator()
    agg.update(_event("RELIANCE", 9, 15, 1, 100.0, high=100.0, low=100.0))
    agg.update(_event("RELIANCE", 9, 15, 15, 105.0, high=105.0, low=100.0))
    agg.update(_event("RELIANCE", 9, 15, 30, 98.0, high=105.0, low=98.0))
    agg.update(_event("RELIANCE", 9, 16, 0, 99.0))  # finalizes 09:15 bar

    bars = agg.get_bars("RELIANCE", "1m")
    row = bars.iloc[0]
    assert row["high"] == 105.0
    assert row["low"] == 98.0


def test_get_bars_excludes_still_forming_bar_by_default():
    agg = LiveBarAggregator()
    agg.update(_event("RELIANCE", 9, 15, 1, 100.0))
    agg.update(_event("RELIANCE", 9, 16, 1, 102.0))  # finalizes 09:15
    agg.update(_event("RELIANCE", 9, 16, 30, 103.0))  # still forming 09:16

    bars = agg.get_bars("RELIANCE", "1m")
    assert len(bars) == 1  # only the finalized 09:15 bar

    with_forming = agg.get_bars("RELIANCE", "1m", include_forming=True)
    assert len(with_forming) == 2


def test_resample_to_5m_aggregates_five_finalized_1m_bars():
    agg = LiveBarAggregator()
    # Five 1-minute bars from 09:15 to 09:19, then a tick in 09:20 to
    # finalize the last of the five.
    prices = [100.0, 101.0, 99.0, 102.0, 103.0]
    for i, price in enumerate(prices):
        agg.update(_event("RELIANCE", 9, 15 + i, 1, price, high=price + 1, low=price - 1))
    agg.update(_event("RELIANCE", 9, 20, 1, 104.0))  # finalizes the 09:19 bar

    bars_1m = agg.get_bars("RELIANCE", "1m")
    assert len(bars_1m) == 5

    bars_5m = agg.get_bars("RELIANCE", "5m")
    assert len(bars_5m) == 1
    row = bars_5m.iloc[0]
    assert row["open"] == 100.0        # first bar's open
    assert row["close"] == 103.0       # last bar's close
    assert row["high"] == max(p + 1 for p in prices)
    assert row["low"] == min(p - 1 for p in prices)


def test_symbols_are_tracked_independently():
    agg = LiveBarAggregator()
    agg.update(_event("RELIANCE", 9, 15, 1, 100.0))
    agg.update(_event("TCS", 9, 15, 1, 4000.0))
    agg.update(_event("RELIANCE", 9, 16, 1, 101.0))  # only finalizes RELIANCE's bar

    assert len(agg.get_bars("RELIANCE", "1m")) == 1
    assert len(agg.get_bars("TCS", "1m")) == 0


def test_zero_or_missing_close_is_ignored_not_finalized():
    agg = LiveBarAggregator()
    assert agg.update({"symbol": "RELIANCE", "ts": _ts_ms(9, 15), "close": 0}) is False
    assert agg.update({"symbol": "RELIANCE", "ts": _ts_ms(9, 15)}) is False
    assert agg.get_bars("RELIANCE", "1m").empty


def test_clear_resets_one_symbol_without_touching_others():
    agg = LiveBarAggregator()
    agg.update(_event("RELIANCE", 9, 15, 1, 100.0))
    agg.update(_event("RELIANCE", 9, 16, 1, 101.0))
    agg.update(_event("TCS", 9, 15, 1, 4000.0))
    agg.update(_event("TCS", 9, 16, 1, 4001.0))

    agg.clear("RELIANCE")
    assert agg.get_bars("RELIANCE", "1m").empty
    assert len(agg.get_bars("TCS", "1m")) == 1


def test_clear_all_resets_everything():
    agg = LiveBarAggregator()
    agg.update(_event("RELIANCE", 9, 15, 1, 100.0))
    agg.update(_event("RELIANCE", 9, 16, 1, 101.0))
    agg.clear()
    assert agg.get_bars("RELIANCE", "1m").empty


# ── merge_live_onto_history ──────────────────────────────────────────────

def _hist_df(rows: list[tuple]) -> pd.DataFrame:
    idx = [pd.Timestamp(ts, tz="UTC") for ts, *_ in rows]
    data = [{"open": o, "high": h, "low": l, "close": c, "volume": v} for _, o, h, l, c, v in rows]
    return pd.DataFrame(data, index=pd.DatetimeIndex(idx, name="ts"))


def test_merge_returns_base_when_live_is_empty():
    base = _hist_df([("2026-08-20 09:15", 100, 101, 99, 100.5, 1000)])
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    merged = merge_live_onto_history(base, empty)
    assert len(merged) == 1


def test_merge_returns_live_when_base_is_empty():
    live = _hist_df([("2026-08-24 09:15", 200, 201, 199, 200.5, 500)])
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    merged = merge_live_onto_history(empty, live)
    assert len(merged) == 1


def test_merge_drops_overlapping_base_rows_in_favour_of_live():
    base = _hist_df([
        ("2026-08-20 09:15", 100, 101, 99, 100.5, 1000),
        ("2026-08-24 09:15", 150, 151, 149, 150.0, 900),   # stale/partial "today" row from the historical fetch
    ])
    live = _hist_df([
        ("2026-08-24 09:15", 150, 155, 149, 154.0, 1200),  # supersedes the stale row above
        ("2026-08-24 09:16", 154, 156, 153, 155.0, 800),
    ])
    merged = merge_live_onto_history(base, live)
    assert len(merged) == 3  # the one prior-day row + two live rows
    assert merged.loc[pd.Timestamp("2026-08-24 09:15", tz="UTC"), "close"] == 154.0
