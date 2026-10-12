"""Live 1-minute bar recording (data_engine/live_bars.BarRecorder)."""
from __future__ import annotations

import pandas as pd

from data_engine.live_bars import BarRecorder, LiveBarAggregator


def _bar(ts: str, o: float, h: float, lo: float, c: float, v: int = 100) -> dict:
    return {"ts": pd.Timestamp(ts), "open": o, "high": h, "low": lo, "close": c, "volume": v}


def test_append_and_load_one_minute(tmp_path):
    rec = BarRecorder(tmp_path)
    rec.append("TCS", _bar("2026-10-12 09:15+05:30", 100, 101, 99, 100.5))
    rec.append("TCS", _bar("2026-10-12 09:16+05:30", 100.5, 102, 100, 101.5))
    assert rec.days() == ["2026-10-12"] and rec.symbols() == ["TCS"]
    lines = (tmp_path / "2026-10-12" / "TCS.csv").read_text().splitlines()
    assert lines[0] == "ts,open,high,low,close,volume" and len(lines) == 3
    df = rec.load("TCS")
    assert len(df) == 2 and str(df.index.tz) == "UTC"
    assert df["close"].tolist() == [100.5, 101.5]


def test_files_are_split_by_ist_date(tmp_path):
    rec = BarRecorder(tmp_path)
    # 20:00 UTC on the 11th is 01:30 IST on the 12th
    rec.append("TCS", _bar("2026-10-11 20:00Z", 1, 1, 1, 1))
    assert rec.days() == ["2026-10-12"]


def test_resample_never_spans_two_sessions(tmp_path):
    rec = BarRecorder(tmp_path)
    for day in ("2026-10-09", "2026-10-12"):
        for i in range(5):
            ts = pd.Timestamp(f"{day} 15:25+05:30") + pd.Timedelta(minutes=i)
            rec.append("TCS", _bar(ts, 100 + i, 101 + i, 99 + i, 100.5 + i, 10))
    df = rec.load("TCS", "5m")
    assert df["volume"].sum() == 100
    ist_days = sorted(set(df.index.tz_convert("Asia/Kolkata").date.astype(str)))
    assert ist_days == ["2026-10-09", "2026-10-12"]
    assert rec.load("TCS", "1m", days=1).index.tz_convert("Asia/Kolkata")[0].day == 12


def test_load_unknown_symbol_is_empty(tmp_path):
    assert BarRecorder(tmp_path).load("NOPE").empty


def _ms(ts: str) -> int:
    return int(pd.Timestamp(ts).timestamp() * 1000)


def test_aggregator_last_bar():
    agg = LiveBarAggregator()
    assert agg.last_bar("TCS") is None
    agg.update({"symbol": "TCS", "ts": _ms("2026-10-12 09:15:10+05:30"), "close": 100.0, "volume": 5})
    closed = agg.update({"symbol": "TCS", "ts": _ms("2026-10-12 09:16:01+05:30"),
                         "close": 101.0, "volume": 5})
    assert closed
    bar = agg.last_bar("TCS")
    assert bar["close"] == 100.0 and set(bar) == {"ts", "open", "high", "low", "close", "volume"}
