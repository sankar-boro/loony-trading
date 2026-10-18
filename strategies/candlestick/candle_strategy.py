import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.pattern_detector import CandlestickPatternDetector, ChartPatternDetector


class CandlestickPatternStrategy(BaseStrategy):
    """
    Detects candlestick patterns + chart patterns and fires signals on high-confidence ones.
    Requires trend context filter to avoid trading against major trend.
    """
    name = "candle_patterns"
    category = "price_action"
    preferred_regimes = ["all"]
    default_atr_stop = 1.5
    default_atr_target = 2.5

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.min_strength = self.param("pattern_min_strength", 0.65)
        self.candle_detector = CandlestickPatternDetector()
        self.chart_detector = ChartPatternDetector()

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, 50):
            return None

        candle_signals = self.candle_detector.detect_all(df)
        chart_signals = self.chart_detector.detect_double_top_bottom(df)
        chart_signals += self.chart_detector.detect_head_and_shoulders(df)

        all_signals = candle_signals + chart_signals
        if not all_signals:
            return None

        # Use most recent high-confidence signal
        recent = [s for s in all_signals if s.bar_index >= len(df) - 3 and s.strength >= self.min_strength]
        if not recent:
            return None

        best = max(recent, key=lambda s: s.strength)
        price = df["close"].iloc[-1]

        if best.direction == 1:
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=best.strength,
                metadata={"pattern": best.name},
            )

        if best.direction == -1:
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=best.strength,
                metadata={"pattern": best.name},
            )

        return None
