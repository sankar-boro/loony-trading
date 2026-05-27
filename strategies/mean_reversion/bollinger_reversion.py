import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class BollingerReversionStrategy(BaseStrategy):
    """
    Buy at lower band touch with RSI confirmation; sell at upper band.
    Uses %B to quantify position within bands.
    """
    name = "bollinger_reversion"
    category = "mean_reversion"
    preferred_regimes = ["ranging"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.period = cfg.get("bb_period", 20)
        self.std_dev = cfg.get("bb_std", 2.0)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.period + 5):
            return None

        upper, mid, lower = TI.bollinger_bands(df["close"], self.period, self.std_dev)
        rsi = TI.rsi(df["close"], 14)
        price = df["close"].iloc[-1]
        bb_pct = (price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1] or 1)

        if bb_pct < 0.05 and rsi.iloc[-1] < 40:
            sl = lower.iloc[-1] - TI.atr(df, 14).iloc[-1]
            tp = mid.iloc[-1]
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=1.0 - bb_pct,
                metadata={"bb_pct": bb_pct},
            )

        if bb_pct > 0.95 and rsi.iloc[-1] > 60:
            sl = upper.iloc[-1] + TI.atr(df, 14).iloc[-1]
            tp = mid.iloc[-1]
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=bb_pct,
                metadata={"bb_pct": bb_pct},
            )

        return None
