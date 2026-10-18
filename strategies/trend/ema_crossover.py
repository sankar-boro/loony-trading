import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class EmaCrossoverStrategy(BaseStrategy):
    """
    EMA fast/slow crossover with volume confirmation.
    Enters on golden cross / death cross, filtered by ADX trend strength.
    """
    name = "ema_crossover"
    category = "trend"
    preferred_regimes = ["trending"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.fast = self.param("ema_fast", 9)
        self.slow = self.param("ema_slow", 21)
        self.adx_min = self.param("adx_min", 20)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, min_bars=self.slow + 10):
            return None

        ema_fast = TI.ema(df["close"], self.fast)
        ema_slow = TI.ema(df["close"], self.slow)
        adx_vals, _, _ = TI.adx(df)

        cross_now = ema_fast.iloc[-1] > ema_slow.iloc[-1]
        cross_prev = ema_fast.iloc[-2] > ema_slow.iloc[-2]
        adx_ok = adx_vals.iloc[-1] >= self.adx_min

        if not adx_ok:
            return None

        price = df["close"].iloc[-1]

        if not cross_prev and cross_now:  # golden cross
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(adx_vals.iloc[-1] / 50, 1.0),
            )

        if cross_prev and not cross_now:  # death cross
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(adx_vals.iloc[-1] / 50, 1.0),
            )

        return None

    def should_exit(self, df: pd.DataFrame, direction: int, bars_held: int) -> Optional[str]:
        """Exit on the opposite crossover."""
        base = super().should_exit(df, direction, bars_held)
        if base or not self.validate_df(df, self.slow + 2):
            return base
        fast_above = TI.ema(df["close"], self.fast).iloc[-1] > TI.ema(df["close"], self.slow).iloc[-1]
        if direction == 1 and not fast_above:
            return "EMA death cross"
        if direction == -1 and fast_above:
            return "EMA golden cross"
        return None
