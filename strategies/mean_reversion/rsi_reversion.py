import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class RsiReversionStrategy(BaseStrategy):
    """
    Enter long when RSI is oversold (< oversold_level) and turning up.
    Enter short when RSI is overbought (> overbought_level) and turning down.
    """
    name = "rsi_mean_reversion"
    category = "mean_reversion"
    preferred_regimes = ["ranging"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.oversold = cfg.get("rsi_oversold", 30)
        self.overbought = cfg.get("rsi_overbought", 70)
        self.period = cfg.get("rsi_period", 14)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.period + 5):
            return None

        rsi = TI.rsi(df["close"], self.period)
        price = df["close"].iloc[-1]

        oversold_exit = rsi.iloc[-2] < self.oversold and rsi.iloc[-1] > rsi.iloc[-2]
        overbought_exit = rsi.iloc[-2] > self.overbought and rsi.iloc[-1] < rsi.iloc[-2]

        if oversold_exit:
            sl, tp = self._atr_stops(df, 1, atr_sl_mult=1.5, atr_tp_mult=2.5)
            confidence = (self.oversold - rsi.iloc[-2]) / self.oversold
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(confidence, 1.0),
            )

        if overbought_exit:
            sl, tp = self._atr_stops(df, -1, atr_sl_mult=1.5, atr_tp_mult=2.5)
            confidence = (rsi.iloc[-2] - self.overbought) / (100 - self.overbought)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(confidence, 1.0),
            )

        return None
