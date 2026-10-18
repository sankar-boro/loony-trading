import pandas as pd
import numpy as np
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from utils.math_utils import rolling_zscore


class ZscoreReversionStrategy(BaseStrategy):
    """
    Trade when price z-score is extreme (>±entry_z), targeting mean reversion.
    """
    name = "zscore_reversion"
    category = "mean_reversion"
    preferred_regimes = ["ranging"]
    default_atr_stop = 1.5
    default_atr_target = 2.0

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.window = self.param("zscore_window", 20)
        self.entry_z = self.param("zscore_entry", 2.0)
        self.exit_z = self.param("zscore_exit", 0.5)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.window + 5):
            return None

        zscores = rolling_zscore(df["close"].values, self.window)
        z = zscores[-1]
        price = df["close"].iloc[-1]

        if z < -self.entry_z:
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(abs(z) / 4, 1.0),
                metadata={"zscore": round(z, 3)},
            )

        if z > self.entry_z:
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(abs(z) / 4, 1.0),
                metadata={"zscore": round(z, 3)},
            )

        return None

    def should_exit(self, df: pd.DataFrame, direction: int, bars_held: int) -> Optional[str]:
        """Exit once the z-score has reverted to within ±exit_z of the mean."""
        base = super().should_exit(df, direction, bars_held)
        if base or not self.validate_df(df, self.window + 5):
            return base
        z = rolling_zscore(df["close"].values, self.window)[-1]
        if (direction == 1 and z > -self.exit_z) or (direction == -1 and z < self.exit_z):
            return f"z-score reverted ({z:+.2f})"
        return None
