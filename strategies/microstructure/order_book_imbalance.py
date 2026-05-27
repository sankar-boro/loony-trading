import pandas as pd
from typing import Optional
from strategies.base import BaseStrategy, Signal, SignalType
from data_engine.orderbook import OrderBookSnapshot


class OrderBookImbalanceStrategy(BaseStrategy):
    """
    Trades based on sustained order book imbalance and whale pressure.
    High imbalance + whale buying pressure → long; inverse → short.
    """
    name = "order_book_imbalance"
    category = "microstructure"
    preferred_regimes = ["all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.imbalance_threshold = cfg.get("ob_imbalance_threshold", 0.3)
        self.whale_threshold_usd = cfg.get("whale_threshold_usd", 100_000)
        self.depth = cfg.get("ob_depth", 10)

    def generate_signal(self, df: pd.DataFrame, symbol: str,
                         orderbook: Optional[OrderBookSnapshot] = None) -> Optional[Signal]:
        if orderbook is None or not self.validate_df(df, 10):
            return None

        imbalance = orderbook.imbalance(self.depth)
        whale = orderbook.whale_pressure(self.whale_threshold_usd)
        price = df["close"].iloc[-1]

        score = 0.6 * imbalance + 0.4 * whale

        if score > self.imbalance_threshold:
            sl, tp = self._atr_stops(df, 1, atr_sl_mult=1.2, atr_tp_mult=1.8)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(abs(score), 1.0),
                metadata={"imbalance": round(imbalance, 3), "whale": round(whale, 3)},
            )

        if score < -self.imbalance_threshold:
            sl, tp = self._atr_stops(df, -1, atr_sl_mult=1.2, atr_tp_mult=1.8)
            return Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=price,
                stop_loss=sl, take_profit=tp,
                confidence=min(abs(score), 1.0),
                metadata={"imbalance": round(imbalance, 3), "whale": round(whale, 3)},
            )

        return None
