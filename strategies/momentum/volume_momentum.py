import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class VolumeMomentumStrategy(BaseStrategy):
    """
    Price breakout confirmed by volume spike (>2x average).
    OBV divergence cross used as entry trigger.
    """
    name = "volume_momentum"
    category = "momentum"
    preferred_regimes = ["trending", "volatile"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.vol_spike = cfg.get("vol_spike_mult", 2.0)
        self.price_pct = cfg.get("price_move_pct", 0.01)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, 30):
            return None

        vol_avg = df["volume"].rolling(20).mean()
        vol_spike = df["volume"].iloc[-1] > vol_avg.iloc[-1] * self.vol_spike
        price_move = df["close"].pct_change(1).iloc[-1]

        obv = TI.obv(df)
        obv_rising = obv.iloc[-1] > obv.iloc[-3]
        obv_falling = obv.iloc[-1] < obv.iloc[-3]

        price = df["close"].iloc[-1]

        if vol_spike and price_move > self.price_pct and obv_rising:
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp, confidence=0.72,
                metadata={"vol_ratio": round(float(df["volume"].iloc[-1] / vol_avg.iloc[-1]), 2)},
            )

        if vol_spike and price_move < -self.price_pct and obv_falling:
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp, confidence=0.72,
                metadata={"vol_ratio": round(float(df["volume"].iloc[-1] / vol_avg.iloc[-1]), 2)},
            )

        return None
