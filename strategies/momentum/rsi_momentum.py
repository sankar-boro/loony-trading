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

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.rsi_period = self.param("rsi_period", 14)
        self.ema_period = self.param("ema_period", 50)
        self.exit_buffer = self.param("exit_buffer", 5.0)   # exit when RSI is this far back through 50

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, 30):
            return None

        rsi = TI.rsi(df["close"], self.rsi_period)
        price = df["close"].iloc[-1]

        crossed_50_up = rsi.iloc[-2] < 50 and rsi.iloc[-1] > 50
        crossed_50_dn = rsi.iloc[-2] > 50 and rsi.iloc[-1] < 50

        # EMA trend filter
        ema50 = TI.ema(df["close"], self.ema_period)
        above_ema = price > ema50.iloc[-1]
        # Strength: momentum past 50 and distance from the trend EMA (ATRs)
        atr = TI.atr(df, 14).iloc[-1] or 1e-9
        strength = (0.5 * self._unit(abs(rsi.iloc[-1] - 50) / 10)
                    + 0.5 * self._unit(abs(price - ema50.iloc[-1]) / atr / 2))

        if crossed_50_up and above_ema:
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp, confidence=self.scaled_confidence(strength),
            )

        if crossed_50_dn and not above_ema:
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp, confidence=self.scaled_confidence(strength),
            )

        return None

    def should_exit(self, df: pd.DataFrame, direction: int, bars_held: int) -> Optional[str]:
        """Exit when RSI falls back through 50 against the position."""
        base = super().should_exit(df, direction, bars_held)
        if base or not self.validate_df(df, 30):
            return base
        rsi = TI.rsi(df["close"], self.rsi_period).iloc[-1]
        if direction == 1 and rsi < 50 - self.exit_buffer:
            return f"RSI back below {50 - self.exit_buffer:.0f}"
        if direction == -1 and rsi > 50 + self.exit_buffer:
            return f"RSI back above {50 + self.exit_buffer:.0f}"
        return None
