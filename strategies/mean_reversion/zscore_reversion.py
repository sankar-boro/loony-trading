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

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.window = cfg.get("zscore_window", 20)
        self.entry_z = cfg.get("zscore_entry", 2.0)
        self.exit_z = cfg.get("zscore_exit", 0.5)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.window + 5):
            return None

        zscores = rolling_zscore(df["close"].values, self.window)
        z = zscores[-1]
        price = df["close"].iloc[-1]

        if z < -self.entry_z:
            sl, tp = self._atr_stops(df, 1, atr_sl_mult=1.5, atr_tp_mult=2.0)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(abs(z) / 4, 1.0),
                metadata={"zscore": round(z, 3)},
            )

        if z > self.entry_z:
            sl, tp = self._atr_stops(df, -1, atr_sl_mult=1.5, atr_tp_mult=2.0)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(abs(z) / 4, 1.0),
                metadata={"zscore": round(z, 3)},
            )

        return None
