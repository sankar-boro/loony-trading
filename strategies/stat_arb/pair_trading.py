import pandas as pd
import numpy as np
from typing import Optional, Tuple
from strategies.base import BaseStrategy, Signal, SignalType
from utils.math_utils import rolling_zscore


class PairTradingStrategy(BaseStrategy):
    """
    Cointegration-based pair trading.
    Trades spread mean reversion when z-score is extreme.
    Generates TWO signals (long leg + short leg).
    """
    name = "pair_trading"
    category = "stat_arb"
    preferred_regimes = ["ranging", "all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.entry_z = cfg.get("pair_entry_z", 2.0)
        self.exit_z = cfg.get("pair_exit_z", 0.0)
        self.hedge_window = cfg.get("pair_hedge_window", 60)

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        # PairTradingStrategy.generate_pair_signals is the real entry point
        return None

    def generate_pair_signals(
        self, df_a: pd.DataFrame, df_b: pd.DataFrame,
        symbol_a: str, symbol_b: str,
    ) -> Tuple[Optional[Signal], Optional[Signal]]:
        if len(df_a) < self.hedge_window + 10 or len(df_b) < self.hedge_window + 10:
            return None, None

        # Align on common index
        merged = pd.DataFrame({
            "a": df_a["close"],
            "b": df_b["close"],
        }).dropna()

        if len(merged) < self.hedge_window + 10:
            return None, None

        hedge_ratio = self._rolling_hedge_ratio(merged["a"], merged["b"])
        spread = merged["a"] - hedge_ratio * merged["b"]
        z = rolling_zscore(spread.values, 20)[-1]

        if np.isnan(z):
            return None, None

        price_a = df_a["close"].iloc[-1]
        price_b = df_b["close"].iloc[-1]

        if z > self.entry_z:
            # spread too high: short A, long B
            sig_a = Signal(
                strategy=self.name, symbol=symbol_a,
                signal_type=SignalType.SELL, price=price_a,
                stop_loss=price_a * 1.02, take_profit=price_a * 0.98,
                confidence=min(abs(z) / 4, 1.0),
                metadata={"spread_z": round(z, 3), "pair": symbol_b},
            )
            sig_b = Signal(
                strategy=self.name, symbol=symbol_b,
                signal_type=SignalType.BUY, price=price_b,
                stop_loss=price_b * 0.98, take_profit=price_b * 1.02,
                confidence=min(abs(z) / 4, 1.0),
                metadata={"spread_z": round(z, 3), "pair": symbol_a},
            )
            return sig_a, sig_b

        if z < -self.entry_z:
            # spread too low: long A, short B
            sig_a = Signal(
                strategy=self.name, symbol=symbol_a,
                signal_type=SignalType.BUY, price=price_a,
                stop_loss=price_a * 0.98, take_profit=price_a * 1.02,
                confidence=min(abs(z) / 4, 1.0),
                metadata={"spread_z": round(z, 3), "pair": symbol_b},
            )
            sig_b = Signal(
                strategy=self.name, symbol=symbol_b,
                signal_type=SignalType.SELL, price=price_b,
                stop_loss=price_b * 1.02, take_profit=price_b * 0.98,
                confidence=min(abs(z) / 4, 1.0),
                metadata={"spread_z": round(z, 3), "pair": symbol_a},
            )
            return sig_a, sig_b

        return None, None

    def _rolling_hedge_ratio(self, a: pd.Series, b: pd.Series) -> float:
        w = self.hedge_window
        a_w = a.iloc[-w:].values
        b_w = b.iloc[-w:].values
        return float(np.polyfit(b_w, a_w, 1)[0])
