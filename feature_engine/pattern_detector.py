import numpy as np
import pandas as pd
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class PatternSignal:
    name: str
    direction: int    # 1 = bullish, -1 = bearish
    strength: float   # 0-1
    bar_index: int


class CandlestickPatternDetector:
    """Detects candlestick reversal and continuation patterns."""

    def detect_all(self, df: pd.DataFrame) -> List[PatternSignal]:
        signals = []
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        body = (c - o).abs()
        full_range = (h - l).replace(0, np.nan)
        body_pct = body / full_range

        for i in range(2, len(df)):
            idx = df.index[i]
            signals += self._engulfing(o, c, body, i, idx)
            signals += self._doji(body_pct, full_range, i, idx)
            signals += self._hammer(o, h, l, c, body, full_range, i, idx)
            signals += self._morning_evening_star(o, c, body, i, idx)
            signals += self._three_white_soldiers(o, c, body, i, idx)
        return signals

    def _engulfing(self, o, c, body, i, idx) -> List[PatternSignal]:
        prev_bull = c.iloc[i-1] > o.iloc[i-1]
        curr_bull = c.iloc[i] > o.iloc[i]
        signals = []
        if (not prev_bull and curr_bull and
                c.iloc[i] > o.iloc[i-1] and o.iloc[i] < c.iloc[i-1]):
            signals.append(PatternSignal("bullish_engulfing", 1, 0.8, i))
        if (prev_bull and not curr_bull and
                c.iloc[i] < o.iloc[i-1] and o.iloc[i] > c.iloc[i-1]):
            signals.append(PatternSignal("bearish_engulfing", -1, 0.8, i))
        return signals

    def _doji(self, body_pct, full_range, i, idx) -> List[PatternSignal]:
        if body_pct.iloc[i] < 0.1 and full_range.iloc[i] > 0:
            return [PatternSignal("doji", 0, 0.5, i)]
        return []

    def _hammer(self, o, h, l, c, body, full_range, i, idx) -> List[PatternSignal]:
        signals = []
        lower_wick = min(o.iloc[i], c.iloc[i]) - l.iloc[i]
        upper_wick = h.iloc[i] - max(o.iloc[i], c.iloc[i])
        if (lower_wick > 2 * body.iloc[i] and upper_wick < body.iloc[i] * 0.5):
            direction = 1 if c.iloc[i] > o.iloc[i] else 1
            signals.append(PatternSignal("hammer", direction, 0.7, i))
        if (upper_wick > 2 * body.iloc[i] and lower_wick < body.iloc[i] * 0.5):
            signals.append(PatternSignal("shooting_star", -1, 0.7, i))
        return signals

    def _morning_evening_star(self, o, c, body, i, idx) -> List[PatternSignal]:
        if i < 2:
            return []
        signals = []
        b0 = body.iloc[i-2]
        b1 = body.iloc[i-1]
        b2 = body.iloc[i]
        bearish_0 = c.iloc[i-2] < o.iloc[i-2]
        bullish_2 = c.iloc[i] > o.iloc[i]
        if bearish_0 and b1 < b0 * 0.3 and bullish_2 and b2 > b0 * 0.5:
            signals.append(PatternSignal("morning_star", 1, 0.85, i))
        bullish_0 = c.iloc[i-2] > o.iloc[i-2]
        bearish_2 = c.iloc[i] < o.iloc[i]
        if bullish_0 and b1 < b0 * 0.3 and bearish_2 and b2 > b0 * 0.5:
            signals.append(PatternSignal("evening_star", -1, 0.85, i))
        return signals

    def _three_white_soldiers(self, o, c, body, i, idx) -> List[PatternSignal]:
        if i < 2:
            return []
        signals = []
        all_bull = all(c.iloc[i-k] > o.iloc[i-k] for k in [0, 1, 2])
        ascending = c.iloc[i] > c.iloc[i-1] > c.iloc[i-2]
        if all_bull and ascending:
            signals.append(PatternSignal("three_white_soldiers", 1, 0.75, i))
        all_bear = all(c.iloc[i-k] < o.iloc[i-k] for k in [0, 1, 2])
        descending = c.iloc[i] < c.iloc[i-1] < c.iloc[i-2]
        if all_bear and descending:
            signals.append(PatternSignal("three_black_crows", -1, 0.75, i))
        return signals


class ChartPatternDetector:
    """Detects multi-bar chart patterns using peak/trough analysis."""

    def detect_double_top_bottom(self, df: pd.DataFrame,
                                  window: int = 30) -> List[PatternSignal]:
        signals = []
        c = df["close"]
        highs = self._find_peaks(c, window=5)
        lows = self._find_troughs(c, window=5)

        for i in range(1, len(highs)):
            h1, h2 = highs[i-1], highs[i]
            if (h2 - h1) > 5 and abs(c.iloc[h1] - c.iloc[h2]) / c.iloc[h1] < 0.02:
                signals.append(PatternSignal("double_top", -1, 0.8, h2))

        for i in range(1, len(lows)):
            l1, l2 = lows[i-1], lows[i]
            if (l2 - l1) > 5 and abs(c.iloc[l1] - c.iloc[l2]) / c.iloc[l1] < 0.02:
                signals.append(PatternSignal("double_bottom", 1, 0.8, l2))

        return signals

    def detect_head_and_shoulders(self, df: pd.DataFrame) -> List[PatternSignal]:
        signals = []
        c = df["close"]
        peaks = self._find_peaks(c, window=5)
        if len(peaks) < 3:
            return signals
        for i in range(1, len(peaks) - 1):
            left, head, right = peaks[i-1], peaks[i], peaks[i+1]
            if (c.iloc[head] > c.iloc[left] and c.iloc[head] > c.iloc[right] and
                    abs(c.iloc[left] - c.iloc[right]) / c.iloc[left] < 0.03):
                signals.append(PatternSignal("head_and_shoulders", -1, 0.85, right))
        return signals

    def _find_peaks(self, series: pd.Series, window: int = 5) -> List[int]:
        peaks = []
        for i in range(window, len(series) - window):
            if series.iloc[i] == series.iloc[i-window:i+window+1].max():
                peaks.append(i)
        return peaks

    def _find_troughs(self, series: pd.Series, window: int = 5) -> List[int]:
        troughs = []
        for i in range(window, len(series) - window):
            if series.iloc[i] == series.iloc[i-window:i+window+1].min():
                troughs.append(i)
        return troughs
