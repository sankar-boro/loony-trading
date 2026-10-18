import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class AtrBreakoutStrategy(BaseStrategy):
    """
    Volatility squeeze breakout: trades when ATR expands after compression.
    Keltner/BB squeeze detects low-vol environments before breakout.
    """
    name = "breakout_atr"
    category = "breakout"
    preferred_regimes = ["volatile"]
    default_atr_stop = 1.5
    default_atr_target = 3.0

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.squeeze_window = self.param("squeeze_window", 20)
        self.expansion_mult = self.param("atr_expansion_mult", 1.5)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.squeeze_window + 10):
            return None

        atr = TI.atr(df, 14)
        avg_atr = atr.rolling(self.squeeze_window).mean()
        atr_ratio = atr / avg_atr.replace(0, float("nan"))

        # ATR expanding after squeeze
        in_expansion = atr_ratio.iloc[-1] > self.expansion_mult
        was_compressed = atr_ratio.iloc[-3:].min() < 0.8

        if not (in_expansion and was_compressed):
            return None

        price = df["close"].iloc[-1]
        prev_close = df["close"].iloc[-2]
        direction = 1 if price > prev_close else -1

        sl, tp = self._atr_stops(df, direction)
        sig_type = SignalType.BUY if direction == 1 else SignalType.SELL

        return Signal(
            strategy=self.name, symbol=symbol,
            signal_type=sig_type, price=price,
            stop_loss=sl, take_profit=tp,
            confidence=min(float(atr_ratio.iloc[-1]) / 3, 1.0),
            metadata={"atr_ratio": round(float(atr_ratio.iloc[-1]), 3)},
        )
