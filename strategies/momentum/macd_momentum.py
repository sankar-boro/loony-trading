import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class MacdMomentumStrategy(BaseStrategy):
    """
    MACD signal line cross with histogram acceleration confirmation.
    Avoids false signals with volume filter.
    """
    name = "macd_momentum"
    category = "momentum"
    preferred_regimes = ["trending"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.fast = cfg.get("macd_fast", 12)
        self.slow = cfg.get("macd_slow", 26)
        self.signal = cfg.get("macd_signal", 9)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.slow + 10):
            return None

        macd, signal, hist = TI.macd(df["close"], self.fast, self.slow, self.signal)
        vol_ratio = df["volume"].iloc[-1] / df["volume"].rolling(20).mean().iloc[-1]

        cross_up = hist.iloc[-2] < 0 and hist.iloc[-1] > 0
        cross_dn = hist.iloc[-2] > 0 and hist.iloc[-1] < 0
        vol_ok = vol_ratio > 1.1
        hist_accel = abs(hist.iloc[-1]) > abs(hist.iloc[-2])

        price = df["close"].iloc[-1]

        if cross_up and vol_ok:
            sl, tp = self._atr_stops(df, 1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=0.7 + (0.15 if hist_accel else 0),
                metadata={"macd": round(float(macd.iloc[-1]), 6), "vol_ratio": round(vol_ratio, 2)},
            )

        if cross_dn and vol_ok:
            sl, tp = self._atr_stops(df, -1)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=0.7 + (0.15 if hist_accel else 0),
                metadata={"macd": round(float(macd.iloc[-1]), 6), "vol_ratio": round(vol_ratio, 2)},
            )

        return None
