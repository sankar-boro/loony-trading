import pandas as pd
import numpy as np
from typing import Optional, List
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class SupportResistanceBreakoutStrategy(BaseStrategy):
    """
    Identifies key S/R levels via local swing-highs/lows and trades confirmed breakouts.
    """
    name = "sr_breakout"
    category = "breakout"
    preferred_regimes = ["trending", "volatile"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.swing_window = cfg.get("swing_window", 10)
        self.confirm_bars = cfg.get("confirm_bars", 2)
        self.min_touches = cfg.get("sr_min_touches", 2)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, 60):
            return None

        levels = self._find_levels(df)
        if not levels:
            return None

        price = df["close"].iloc[-1]
        atr = TI.atr(df, 14).iloc[-1]
        tolerance = atr * 0.5

        for level, touches in levels:
            if touches < self.min_touches:
                continue
            # resistance breakout
            if df["close"].iloc[-self.confirm_bars - 1] < level and price > level + tolerance:
                sl, tp = self._atr_stops(df, 1)
                return Signal(
                    strategy=self.name, symbol=symbol,
                    signal_type=SignalType.BUY, price=price,
                    stop_loss=sl, take_profit=tp,
                    confidence=0.7 + min(touches * 0.05, 0.25),
                    metadata={"level": level, "touches": touches},
                )
            # support breakdown
            if df["close"].iloc[-self.confirm_bars - 1] > level and price < level - tolerance:
                sl, tp = self._atr_stops(df, -1)
                return Signal(
                    strategy=self.name, symbol=symbol,
                    signal_type=SignalType.SELL, price=price,
                    stop_loss=sl, take_profit=tp,
                    confidence=0.7 + min(touches * 0.05, 0.25),
                    metadata={"level": level, "touches": touches},
                )
        return None

    def _find_levels(self, df: pd.DataFrame) -> List[tuple]:
        w = self.swing_window
        highs = df["high"].values
        lows = df["low"].values
        levels = []
        for i in range(w, len(df) - w):
            if highs[i] == max(highs[i-w:i+w]):
                levels.append(highs[i])
            if lows[i] == min(lows[i-w:i+w]):
                levels.append(lows[i])
        level_counts = []
        tolerance = df["close"].mean() * 0.005
        used = set()
        for i, lv in enumerate(levels):
            if i in used:
                continue
            touches = sum(1 for j, lv2 in enumerate(levels) if abs(lv - lv2) < tolerance)
            level_counts.append((lv, touches))
            used.update(j for j, lv2 in enumerate(levels) if abs(lv - lv2) < tolerance)
        return sorted(level_counts, key=lambda x: x[1], reverse=True)[:5]
