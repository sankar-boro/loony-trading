import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class RsiMomentumStrategy(BaseStrategy):
    """
    RSI momentum: enter when RSI crosses 50 from below/above with trend bias.
    """
    name = "rsi_momentum"
    category = "momentum"
    preferred_regimes = ["trending"]

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, 30):
            return None

        rsi = TI.rsi(df["close"], 14)
        price = df["close"].iloc[-1]

        crossed_50_up = rsi.iloc[-2] < 50 and rsi.iloc[-1] > 50
        crossed_50_dn = rsi.iloc[-2] > 50 and rsi.iloc[-1] < 50

        # EMA trend filter
        ema50 = TI.ema(df["close"], 50)
        above_ema = price > ema50.iloc[-1]

        if crossed_50_up and above_ema:
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp, confidence=0.65,
            )

        if crossed_50_dn and not above_ema:
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp, confidence=0.65,
            )

        return None
