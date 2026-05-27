import pandas as pd
from typing import Optional, Dict
from strategies.base import BaseStrategy, Signal, SignalType
from feature_engine.indicators import TechnicalIndicators as TI


class MultiTimeframeTrendStrategy(BaseStrategy):
    """
    Requires trend alignment across 3 timeframes before entering.
    High-conviction trade filter.
    """
    name = "mtf_trend"
    category = "trend"
    preferred_regimes = ["trending"]

    def generate_signal(self, df: pd.DataFrame, symbol: str,
                         frames: Dict[str, pd.DataFrame] | None = None) -> Optional[Signal]:
        if frames is None or not self.validate_df(df):
            return None

        directions = []
        for tf, frame in frames.items():
            if len(frame) < 50:
                continue
            ema20 = TI.ema(frame["close"], 20).iloc[-1]
            ema50 = TI.ema(frame["close"], 50).iloc[-1]
            directions.append(1 if ema20 > ema50 else -1)

        if len(directions) < 2:
            return None

        aligned = all(d == directions[0] for d in directions)
        if not aligned:
            return None

        direction = directions[0]
        price = df["close"].iloc[-1]
        sl, tp = self._atr_stops(df, direction)
        sig_type = SignalType.BUY if direction == 1 else SignalType.SELL

        return Signal(
            strategy=self.name, symbol=symbol,
            signal_type=sig_type, price=price,
            stop_loss=sl, take_profit=tp,
            confidence=0.85,
            metadata={"tf_alignment": len(directions)},
        )
