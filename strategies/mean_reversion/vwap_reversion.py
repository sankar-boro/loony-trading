import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class VwapReversionStrategy(BaseStrategy):
    """
    Intraday VWAP reversion: buy when price dips >1 std below VWAP; sell above.
    """
    name = "vwap_reversion"
    category = "mean_reversion"
    preferred_regimes = ["ranging", "low_volatility"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.std_mult = cfg.get("vwap_std_mult", 1.5)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, 30):
            return None

        upper, vwap, lower = TI.vwap_bands(df, self.std_mult)
        price = df["close"].iloc[-1]
        atr = TI.atr(df, 14).iloc[-1]

        if price < lower.iloc[-1]:
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=price - 1.5 * atr,
                take_profit=vwap.iloc[-1],
                confidence=0.65,
                metadata={"vwap": round(vwap.iloc[-1], 4)},
            )

        if price > upper.iloc[-1]:
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=price + 1.5 * atr,
                take_profit=vwap.iloc[-1],
                confidence=0.65,
                metadata={"vwap": round(vwap.iloc[-1], 4)},
            )

        return None
