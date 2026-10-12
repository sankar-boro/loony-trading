from datetime import time as dt_time
from typing import Optional

import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI

_NSE_OPEN_WINDOW = (dt_time(9, 0), dt_time(9, 30))  # tolerance around the 09:15 IST open


class RangeBreakoutStrategy(BaseStrategy):
    """
    Opening range breakout.

    On genuine NSE intraday data (a DatetimeIndex whose first bar of the
    day falls near the 09:15 IST open), this is session-anchored: the
    "opening range" is the first `range_minutes` minutes of *today's*
    session, and breakouts are only evaluated against bars later the
    same session. The previous implementation defined the range as
    "first N bars counted backward from the most recent bar" — on
    intraday data that's not anchored to market open at all (it slides
    with whenever the strategy happens to run), and its own docstring
    called it an "Asian session... works on hourly crypto data" window,
    which was never NSE's actual opening-range convention. See
    docs/appendix/intraday-audit.md §3.

    Falls back to the original bar-count window for data with no
    NSE-session-like clustering — daily bars (one row per day) or
    continuous 24/7 data such as crypto, where "today's 09:15 IST open"
    isn't a meaningful anchor and changing behaviour is out of scope for
    the NSE intraday fix this class exists for.
    """
    name = "range_breakout"
    category = "breakout"
    preferred_regimes = ["ranging", "trending"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.range_bars = cfg.get("range_bars", 8)          # legacy bar-count fallback
        self.range_minutes = cfg.get("range_minutes", 15)    # NSE opening-range window

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        session = self._session_range(df)
        if session is not None:
            session_high, session_low, post_range = session
            price = post_range["close"].iloc[-1]
        else:
            if not self.validate_df(df, self.range_bars + 5):
                return None
            range_bars = df.iloc[-(self.range_bars + 5):-5]
            session_high = range_bars["high"].max()
            session_low = range_bars["low"].min()
            price = df["close"].iloc[-1]

        if not self.validate_df(df, 20):
            return None
        atr = TI.atr(df, 14).iloc[-1]
        buffer = atr * 0.1

        if price > session_high + buffer:
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp, confidence=0.68,
                metadata={"session_high": session_high, "session_low": session_low},
            )

        if price < session_low - buffer:
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp, confidence=0.68,
                metadata={"session_high": session_high, "session_low": session_low},
            )

        return None

    def _session_range(self, df: pd.DataFrame):
        """Returns (session_high, session_low, bars_after_range) for
        today's NSE session, or None if `df` doesn't look like NSE
        intraday data — the caller falls back to the legacy bar-count
        window in that case."""
        if not isinstance(df.index, pd.DatetimeIndex):
            return None

        today = df.index[-1].normalize()
        todays_bars = df[df.index.normalize() == today]
        if len(todays_bars) < 2:
            return None  # e.g. daily-bar data: one row per calendar day

        session_start = todays_bars.index[0]
        # Naive timestamps are treated as already being in IST (this
        # project's convention — see e.g. test_microstructure.py's
        # fixtures); tz-aware timestamps are converted explicitly. Real
        # Upstox intraday data is always tz-aware UTC.
        local_time = (session_start.tz_convert("Asia/Kolkata").time()
                      if session_start.tzinfo is not None else session_start.time())
        if not (_NSE_OPEN_WINDOW[0] <= local_time <= _NSE_OPEN_WINDOW[1]):
            return None  # doesn't look like an NSE session open — e.g. crypto's 24/7 bars

        range_end = session_start + pd.Timedelta(minutes=self.range_minutes)
        range_window = todays_bars[todays_bars.index < range_end]
        post_range = todays_bars[todays_bars.index >= range_end]
        if range_window.empty or post_range.empty:
            return None

        return range_window["high"].max(), range_window["low"].min(), post_range
