import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class RangeBreakoutStrategy(BaseStrategy):
    """
    Asian session range breakout: define high/low of first N hours,
    then trade breakout for the remainder of the session.
    Works on hourly crypto data.
    """
    name = "range_breakout"
    category = "breakout"
    preferred_regimes = ["ranging", "trending"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.range_bars = cfg.get("range_bars", 8)  # first 8 hours = Asian session

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.range_bars + 5):
            return None

        range_bars = df.iloc[-(self.range_bars + 5):-5]
        session_high = range_bars["high"].max()
        session_low = range_bars["low"].min()
        price = df["close"].iloc[-1]
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
