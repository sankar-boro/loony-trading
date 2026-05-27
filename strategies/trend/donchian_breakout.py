import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class DonchianBreakoutStrategy(BaseStrategy):
    name = "donchian_breakout"
    category = "trend"
    preferred_regimes = ["trending"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.period = cfg.get("dc_period", 20)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.period + 5):
            return None

        upper, _, lower = TI.donchian_channel(df, self.period)
        price = df["close"].iloc[-1]
        prev_high = df["high"].iloc[-2]
        prev_low = df["low"].iloc[-2]

        if df["close"].iloc[-1] > upper.iloc[-2]:
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp, confidence=0.7,
            )
        if df["close"].iloc[-1] < lower.iloc[-2]:
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp, confidence=0.7,
            )
        return None
