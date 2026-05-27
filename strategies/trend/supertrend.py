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
        self.period = cfg.get("st_period", 7)
        self.multiplier = cfg.get("st_multiplier", 3.0)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, 30):
            return None

        _, direction = TI.supertrend(df, self.period, self.multiplier)
        prev_dir = direction.iloc[-2]
        curr_dir = direction.iloc[-1]

        if prev_dir == curr_dir:
            return None

        price = df["close"].iloc[-1]
        d = int(curr_dir)
        sl, tp = self._atr_stops(df, d)
        sig_type = SignalType.BUY if d == 1 else SignalType.SELL

        return Signal(
            strategy=self.name, symbol=symbol,
            signal_type=sig_type, price=price,
            stop_loss=sl, take_profit=tp,
            confidence=0.75,
        )
