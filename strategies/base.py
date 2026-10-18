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
    # Default stop / target distance in ATRs; tunable per strategy as the
    # atr_stop_mult / atr_target_mult parameters.
    default_atr_stop: float = 2.0
    default_atr_target: float = 3.0

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.enabled = True
        self.weight = cfg.get("strategies", {}).get("weights", {}).get(self.name, 1.0)
        # Effective parameters, filled by param() — shown on the dashboard
        self.params: dict = {}
        self._param_cfg: dict = (((cfg.get("strategies") or {}).get("params") or {})
                                 .get(self.name) or {})
        self.max_hold_bars = self.param("max_hold_bars", 0)    # time stop; 0 = off
        self.param("atr_stop_mult", self.default_atr_stop)
        self.param("atr_target_mult", self.default_atr_target)

    def param(self, key: str, default):
        """A tunable parameter: strategies.params.<name>.<key> in settings.yaml,
        else the legacy top-level key of the same name, else `default`. The
        value is cast to the default's type and recorded in self.params."""
        if key in self._param_cfg:
            value = self._param_cfg[key]
        elif key in self.cfg and not isinstance(self.cfg[key], dict):
            value = self.cfg[key]
        else:
            value = default
        if default is not None and not isinstance(default, bool):
            try:
                value = type(default)(value)
            except (TypeError, ValueError):
                value = default
        self.params[key] = value
        return value

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """Return a Signal or None if no trade is warranted."""
        ...

    def validate_df(self, df: pd.DataFrame, min_bars: int = 50) -> bool:
        return df is not None and len(df) >= min_bars

    @staticmethod
    def scaled_confidence(strength: float, low: float = 0.55, high: float = 0.85) -> float:
        """Map a setup-strength score in [0, 1] (how far past the threshold,
        how much volume confirmed it, ...) to a confidence in [low, high], so
        a marginal setup ranks below a decisive one."""
        s = min(max(float(strength), 0.0), 1.0)
        return round(low + (high - low) * s, 3)

    @staticmethod
    def _volume_ratio(df: pd.DataFrame, window: int = 20) -> float:
        """Last bar's volume over its `window`-bar average (1.0 without volume)."""
        if "volume" not in df or len(df) < window:
            return 1.0
        avg = df["volume"].iloc[-window:].mean()
        return float(df["volume"].iloc[-1] / avg) if avg > 0 else 1.0

    @staticmethod
    def _unit(x: float) -> float:
        """Clamp to [0, 1]."""
        return min(max(float(x), 0.0), 1.0)

    def should_exit(self, df: pd.DataFrame, direction: int, bars_held: int) -> Optional[str]:
        """Strategy-specific exit for an open position this strategy opened,
        checked on each closed bar (live bot and backtester). Returns a short
        reason to close now, or None. The base version applies the time stop
        (`max_hold_bars`); strategies extend it with their own exit rules."""
        if self.max_hold_bars and bars_held >= self.max_hold_bars:
            return f"time stop ({bars_held} bars)"
        return None

    def _atr_stops(self, df: pd.DataFrame, direction: int,
                   atr_sl_mult: float | None = None,
                   atr_tp_mult: float | None = None) -> tuple[float, float]:
        """Stop and target `atr_stop_mult` / `atr_target_mult` ATRs from the
        close (parameters; class defaults default_atr_stop / default_atr_target),
        unless given explicitly."""
        from feature_engine.indicators import TechnicalIndicators as TI
        if atr_sl_mult is None:
            atr_sl_mult = self.params["atr_stop_mult"]
        if atr_tp_mult is None:
            atr_tp_mult = self.params["atr_target_mult"]
        atr = TI.atr(df, 14).iloc[-1]
        price = df["close"].iloc[-1]
        stop_loss = price - direction * atr * atr_sl_mult
        take_profit = price + direction * atr * atr_tp_mult
        return stop_loss, take_profit
