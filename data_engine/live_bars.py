"""
Live intraday bar aggregator — intraday-gap fix Phase 1
(see docs/intraday_gaps.md §1/§7).

UpstoxFeed already decodes a live-updating 1-minute candle (marketOHLC
"I1" interval) on every tick — see upstox_feed.py:_decode_with_sdk — but
nothing consumed it. main.py's live loop kept scoring strategies against
whatever historical snapshot _load_historical_data() fetched once at bot
startup, for the entire session. This module is the missing bridge: it
tracks that 1-minute stream per symbol, finalizes each 1-minute bar the
moment the next one starts (a bar is only ever "final" once we've
observed the tick that opens the next minute — no look-ahead), and
resamples on demand to any coarser session-aligned timeframe (5m/15m/...)
by plain wall-clock flooring. NSE's 09:15 open is itself aligned to
every common intraday bucket size (555 minutes past midnight is a
multiple of 5 and 15), so no session-anchor offset is needed.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass

import pandas as pd

# ~8h of 1-minute bars — comfortably covers one NSE session (09:15-15:30)
# without unbounded memory growth over a long-running process.
_MAX_BARS_PER_SYMBOL = 500

_RESAMPLE_RULE = {
    "1m": "1min", "1min": "1min",
    "5m": "5min", "10m": "10min", "15m": "15min", "30m": "30min",
    "1h": "60min", "60m": "60min",
}


def timeframe_minutes(timeframe: str) -> int:
    """Minutes per bar for a timeframe string, or 1 if unrecognized
    (safest default — triggers on every finalized 1-min bar rather than
    silently never triggering)."""
    rule = _RESAMPLE_RULE.get(timeframe, timeframe)
    if rule.endswith("min"):
        try:
            return max(1, int(rule[:-3]))
        except ValueError:
            return 1
    return 1


@dataclass
class _Bar:
    ts: "pd.Timestamp"
    open: float
    high: float
    low: float
    close: float
    volume: float


class LiveBarAggregator:
    """Per-symbol rolling buffer of finalized 1-minute bars, built from
    UpstoxFeed candle events (MarketEvent.to_candle_event() shape). Not a
    substitute for historical warmup data — callers merge get_bars()
    onto a pre-fetched historical dataframe (see merge_live_onto_history)."""

    def __init__(self) -> None:
        self._bars: dict[str, deque] = {}
        self._current: dict[str, _Bar] = {}

    def update(self, event: dict) -> bool:
        """Feed one candle event. Returns True iff this call finalized a
        new 1-minute bar (i.e. a bar just closed) — callers use this to
        know when it's actually meaningful to re-score a strategy,
        instead of guessing with a tick-count heuristic."""
        symbol = event.get("symbol")
        ts_ms = event.get("ts")
        if not symbol or not ts_ms:
            return False

        close = event.get("close")
        if close is None or float(close) <= 0:
            return False
        close = float(close)
        o = float(event.get("open") or close)
        h = float(event.get("high") or close)
        l = float(event.get("low") or close)
        v = float(event.get("volume") or 0)

        minute = pd.Timestamp(int(ts_ms), unit="ms", tz="UTC").floor("1min")

        cur = self._current.get(symbol)
        finalized = False
        if cur is not None and cur.ts != minute:
            # A new minute has started — the previous one is now final,
            # never to be revised again.
            self._bars.setdefault(symbol, deque(maxlen=_MAX_BARS_PER_SYMBOL)).append(cur)
            cur = None
            finalized = True

        if cur is None:
            self._current[symbol] = _Bar(ts=minute, open=o, high=h, low=l, close=close, volume=v)
        else:
            cur.high = max(cur.high, h)
            cur.low = min(cur.low, l) if cur.low > 0 else l
            cur.close = close
            # Upstox's per-tick "I1" volume is the bar's own running total
            # as it forms, not a per-tick delta — the latest value already
            # is the correct cumulative-for-this-bar figure.
            cur.volume = v

        return finalized

    def get_bars(self, symbol: str, timeframe: str = "1m",
                 include_forming: bool = False) -> pd.DataFrame:
        """Finalized bars resampled to `timeframe`. Excludes the
        still-forming current bar by default — including a partial bar
        in what a strategy scores against would itself be a form of
        look-ahead-adjacent inconsistency (an incomplete candle isn't
        the same signal as a closed one). Pass include_forming=True only
        for display/live-price use cases where a partial last bar is fine."""
        bars = list(self._bars.get(symbol, ()))
        if include_forming and symbol in self._current:
            bars = bars + [self._current[symbol]]
        if not bars:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame([
            {"ts": b.ts, "open": b.open, "high": b.high, "low": b.low,
             "close": b.close, "volume": b.volume}
            for b in bars
        ]).set_index("ts").sort_index()

        rule = _RESAMPLE_RULE.get(timeframe, timeframe)
        if rule == "1min":
            return df
        return df.resample(rule).agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

    def clear(self, symbol: str | None = None) -> None:
        """Reset for a new session. Call at market open / bot startup —
        stale bars from a previous run must never bleed into a new one."""
        if symbol:
            self._bars.pop(symbol, None)
            self._current.pop(symbol, None)
        else:
            self._bars.clear()
            self._current.clear()


def merge_live_onto_history(base: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    """Splice freshly-aggregated live bars onto a historically-fetched
    dataframe. Any base rows at/after the first live bar's timestamp are
    dropped — today's live data supersedes whatever a stale or partial
    historical fetch returned for the same window, rather than the two
    silently coexisting with duplicate/conflicting rows for the same bar."""
    if live is None or live.empty:
        return base
    if base is None or base.empty:
        return live
    cutoff = live.index.min()
    return pd.concat([base[base.index < cutoff], live])
