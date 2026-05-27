from __future__ import annotations
import pandas as pd
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from utils.timeutils import now_utc


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    HOLD = "hold"


@dataclass
class Signal:
    strategy: str
    symbol: str
    signal_type: SignalType
    price: float
    stop_loss: float
    take_profit: float
    confidence: float          # 0–1
    timeframe: str = "1h"
    metadata: dict = field(default_factory=dict)
    ts: str = field(default_factory=lambda: now_utc().isoformat())

    @property
    def is_entry(self) -> bool:
        return self.signal_type in (SignalType.BUY, SignalType.SELL)

    @property
    def direction(self) -> int:
        return 1 if self.signal_type == SignalType.BUY else -1


class BaseStrategy(ABC):
    name: str = "base"
    category: str = "generic"
    preferred_regimes: list[str] = []  # e.g. ["trending", "ranging"]

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.enabled = True
        self.weight = cfg.get("strategies", {}).get("weights", {}).get(self.name, 1.0)

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """Return a Signal or None if no trade is warranted."""
        ...

    def validate_df(self, df: pd.DataFrame, min_bars: int = 50) -> bool:
        return df is not None and len(df) >= min_bars

    def _atr_stops(self, df: pd.DataFrame, direction: int,
                   atr_sl_mult: float = 2.0,
                   atr_tp_mult: float = 3.0) -> tuple[float, float]:
        from feature_engine.indicators import TechnicalIndicators as TI
        atr = TI.atr(df, 14).iloc[-1]
        price = df["close"].iloc[-1]
        stop_loss = price - direction * atr * atr_sl_mult
        take_profit = price + direction * atr * atr_tp_mult
        return stop_loss, take_profit
