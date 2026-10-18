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
        self.period = self.param("dc_period", 20)
        self.exit_period = self.param("exit_period", 10)    # opposite-channel exit

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.period + 5):
            return None

        upper, _, lower = TI.donchian_channel(df, self.period)
        price = df["close"].iloc[-1]
        prev_high = df["high"].iloc[-2]
        prev_low = df["low"].iloc[-2]

        atr = TI.atr(df, 14).iloc[-1] or 1e-9
        vol = self._unit((self._volume_ratio(df) - 1) / 1.5)

        if df["close"].iloc[-1] > upper.iloc[-2]:
            # Strength: how far past the channel (in ATRs) and volume confirmation
            strength = 0.5 * self._unit((price - upper.iloc[-2]) / atr) + 0.5 * vol
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp, confidence=self.scaled_confidence(strength),
            )
        if df["close"].iloc[-1] < lower.iloc[-2]:
            strength = 0.5 * self._unit((lower.iloc[-2] - price) / atr) + 0.5 * vol
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp, confidence=self.scaled_confidence(strength),
            )
        return None

    def should_exit(self, df: pd.DataFrame, direction: int, bars_held: int) -> Optional[str]:
        """Turtle-style exit: a close through the opposite `exit_period`-bar channel."""
        base = super().should_exit(df, direction, bars_held)
        if base or len(df) < self.exit_period + 2:
            return base
        window = df.iloc[-(self.exit_period + 1):-1]
        close = df["close"].iloc[-1]
        if direction == 1 and close < window["low"].min():
            return f"close below {self.exit_period}-bar low"
        if direction == -1 and close > window["high"].max():
            return f"close above {self.exit_period}-bar high"
        return None
