import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class SupertrendStrategy(BaseStrategy):
    name = "supertrend"
    category = "trend"
    preferred_regimes = ["trending"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.period = self.param("st_period", 7)
        self.multiplier = self.param("st_multiplier", 3.0)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, 30):
            return None

        line, direction = TI.supertrend(df, self.period, self.multiplier)
        prev_dir = direction.iloc[-2]
        curr_dir = direction.iloc[-1]

        if prev_dir == curr_dir:
            return None

        price = df["close"].iloc[-1]
        d = int(curr_dir)
        sl, tp = self._atr_stops(df, d)
        sig_type = SignalType.BUY if d == 1 else SignalType.SELL
        # Strength: distance from the supertrend line (ATRs) and trend strength (ADX)
        atr = TI.atr(df, 14).iloc[-1] or 1e-9
        adx_vals, _, _ = TI.adx(df)
        strength = (0.5 * self._unit(abs(price - line.iloc[-1]) / atr / 2)
                    + 0.5 * self._unit(adx_vals.iloc[-1] / 50))

        return Signal(
            strategy=self.name, symbol=symbol,
            signal_type=sig_type, price=price,
            stop_loss=sl, take_profit=tp,
            confidence=self.scaled_confidence(strength),
        )

    def should_exit(self, df: pd.DataFrame, direction: int, bars_held: int) -> Optional[str]:
        """Exit when the supertrend flips against the position."""
        base = super().should_exit(df, direction, bars_held)
        if base or not self.validate_df(df, 30):
            return base
        _, st_dir = TI.supertrend(df, self.period, self.multiplier)
        if int(st_dir.iloc[-1]) == -direction:
            return "supertrend flipped"
        return None
