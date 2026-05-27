"""
Cumulative Delta Strategy — Order flow imbalance from tick data.

Cumulative Delta = Sum of (Buy Volume - Sell Volume) over a session.

How it works:
- Each trade is classified as aggressive buy (hit the ask) or aggressive sell (hit the bid)
- Running sum reveals who is in control: buyers or sellers
- Delta divergence (price rises but delta falls) = bearish; opposite = bullish
- Used by all institutional prop desks — strongest intraday signal available

Tick classification (without raw L1 tick feed, use approximation):
- Price tick UP → buyer was aggressive (buy volume)
- Price tick DOWN → seller was aggressive (sell volume)
- For OHLCV bars: use (close - open) to estimate net buy/sell pressure

Note: With Upstox WebSocket feed in "full" mode, we get bid/ask data
which allows proper Lee-Ready tick rule classification.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from utils.logger import get_logger

logger = get_logger("cumulative_delta")


@dataclass
class DeltaBar:
    """Single OHLCV bar with delta annotation."""
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_volume: float
    sell_volume: float

    @property
    def delta(self) -> float:
        return self.buy_volume - self.sell_volume

    @property
    def delta_pct(self) -> float:
        total = self.buy_volume + self.sell_volume
        return self.delta / total if total > 0 else 0.0


class DeltaTracker:
    """
    Tracks cumulative delta from live ticks or estimated from OHLCV bars.
    Maintains a rolling window for divergence detection.
    """

    def __init__(self, window: int = 20):
        self.window = window
        self._bars: Deque[DeltaBar] = deque(maxlen=window)
        self._cumulative_delta: float = 0.0
        self._session_delta: float = 0.0

    def add_tick(self, price: float, volume: float, side: str) -> None:
        """Add a classified tick. side = 'buy' or 'sell'."""
        if side == "buy":
            self._cumulative_delta += volume
            self._session_delta    += volume
        else:
            self._cumulative_delta -= volume
            self._session_delta    -= volume

    def add_bar(self, bar: pd.Series) -> None:
        """
        Add an OHLCV bar. Estimates buy/sell split using:
        - Aggressive buy volume ≈ volume * (close - low) / (high - low)  [Lee-Ready approx]
        - Aggressive sell volume = volume - buy volume
        """
        hl = bar["high"] - bar["low"]
        if hl > 0:
            buy_frac = (bar["close"] - bar["low"]) / hl
        else:
            buy_frac = 0.5 if bar["close"] >= bar["open"] else 0.5

        buy_vol  = bar["volume"] * buy_frac
        sell_vol = bar["volume"] * (1.0 - buy_frac)

        db = DeltaBar(
            timestamp=bar.name if isinstance(bar.name, pd.Timestamp) else pd.Timestamp.now(),
            open=bar["open"], high=bar["high"], low=bar["low"], close=bar["close"],
            volume=bar["volume"], buy_volume=buy_vol, sell_volume=sell_vol,
        )
        self._bars.append(db)
        self._cumulative_delta += db.delta
        self._session_delta    += db.delta

    def load_df(self, df: pd.DataFrame) -> None:
        """Load a full OHLCV DataFrame into the tracker."""
        self._bars.clear()
        self._cumulative_delta = 0.0
        for _, row in df.iterrows():
            self.add_bar(row)

    def reset_session(self) -> None:
        self._session_delta = 0.0

    @property
    def cumulative_delta(self) -> float:
        return self._cumulative_delta

    @property
    def session_delta(self) -> float:
        return self._session_delta

    def delta_series(self) -> np.ndarray:
        """Cumulative sum of bar deltas for divergence analysis."""
        deltas = [b.delta for b in self._bars]
        return np.cumsum(deltas)

    def detect_divergence(self) -> Optional[str]:
        """
        Detect price/delta divergence.
        Returns "BULLISH_DIVERGENCE", "BEARISH_DIVERGENCE", or None.
        """
        if len(self._bars) < 5:
            return None

        bars = list(self._bars)
        prices = np.array([b.close for b in bars])
        cum_d  = np.cumsum([b.delta for b in bars])

        price_trend = prices[-1] - prices[-5]
        delta_trend = cum_d[-1] - cum_d[-5]

        # Price rising, delta falling → sellers absorbing → BEARISH
        if price_trend > 0 and delta_trend < -0.1 * abs(cum_d[-5] if cum_d[-5] != 0 else 1):
            return "BEARISH_DIVERGENCE"

        # Price falling, delta rising → buyers absorbing → BULLISH
        if price_trend < 0 and delta_trend > 0.1 * abs(cum_d[-5] if cum_d[-5] != 0 else 1):
            return "BULLISH_DIVERGENCE"

        return None

    def summary(self) -> dict:
        bars = list(self._bars)
        if not bars:
            return {}
        total_buy  = sum(b.buy_volume for b in bars)
        total_sell = sum(b.sell_volume for b in bars)
        return {
            "session_delta": round(self._session_delta, 0),
            "cumulative_delta": round(self._cumulative_delta, 0),
            "total_buy_volume": round(total_buy, 0),
            "total_sell_volume": round(total_sell, 0),
            "buy_sell_ratio": round(total_buy / total_sell, 3) if total_sell > 0 else float("inf"),
            "divergence": self.detect_divergence(),
            "bars": len(bars),
        }


class CumulativeDeltaStrategy(BaseStrategy):
    """
    Trade when cumulative delta confirms price direction OR diverges.

    Entry conditions:
    - Bullish: price > VWAP AND session delta > delta_threshold (buyers in control)
    - Bearish: price < VWAP AND session delta < -delta_threshold (sellers in control)
    - Reversal: delta divergence detected (price vs delta disagree)
    """
    name = "cumulative_delta"
    category = "microstructure"
    preferred_regimes = ["all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        mcfg = cfg.get("microstructure", {}).get("cumulative_delta", {})
        self.delta_threshold    = mcfg.get("delta_threshold_pct", 0.15)   # 15% buy/sell imbalance
        self.divergence_enabled = mcfg.get("divergence_enabled", True)
        self.window             = mcfg.get("window", 20)
        self._trackers: dict = {}  # symbol → DeltaTracker

    def _get_tracker(self, symbol: str) -> DeltaTracker:
        if symbol not in self._trackers:
            self._trackers[symbol] = DeltaTracker(window=self.window)
        return self._trackers[symbol]

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if not self.validate_df(df, self.window):
            return None

        tracker = self._get_tracker(symbol)
        tracker.load_df(df.tail(self.window))

        spot  = df["close"].iloc[-1]
        vwap  = float((df["close"] * df["volume"]).cumsum().iloc[-1] /
                      df["volume"].cumsum().iloc[-1])
        summary = tracker.summary()
        session_delta = summary.get("session_delta", 0.0)
        buy_sell_ratio = summary.get("buy_sell_ratio", 1.0)
        divergence = summary.get("divergence")

        # Imbalance signal
        total_vol = summary.get("total_buy_volume", 1) + summary.get("total_sell_volume", 1)
        imbalance = session_delta / total_vol if total_vol > 0 else 0.0

        signal: Optional[Signal] = None

        # ── Divergence reversal (highest priority) ────────────────────────────
        if self.divergence_enabled and divergence:
            sl, tp = self._atr_stops(df, 1 if divergence == "BULLISH_DIVERGENCE" else -1,
                                     atr_sl_mult=1.0, atr_tp_mult=1.8)
            sig_type = SignalType.BUY if divergence == "BULLISH_DIVERGENCE" else SignalType.SELL
            confidence = 0.72
            signal = Signal(
                strategy=self.name, symbol=symbol,
                signal_type=sig_type, price=spot,
                stop_loss=sl, take_profit=tp,
                confidence=confidence,
                metadata={**summary, "signal_type": divergence},
            )

        # ── Trend confirmation ────────────────────────────────────────────────
        elif imbalance > self.delta_threshold and spot > vwap:
            sl, tp = self._atr_stops(df, 1, atr_sl_mult=1.0, atr_tp_mult=1.5)
            confidence = min(0.55 + abs(imbalance) * 0.5, 0.82)
            signal = Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.BUY, price=spot,
                stop_loss=sl, take_profit=tp,
                confidence=confidence,
                metadata={**summary, "signal_type": "buy_flow_confirmation"},
            )

        elif imbalance < -self.delta_threshold and spot < vwap:
            sl, tp = self._atr_stops(df, -1, atr_sl_mult=1.0, atr_tp_mult=1.5)
            confidence = min(0.55 + abs(imbalance) * 0.5, 0.82)
            signal = Signal(
                strategy=self.name, symbol=symbol,
                signal_type=SignalType.SELL, price=spot,
                stop_loss=sl, take_profit=tp,
                confidence=confidence,
                metadata={**summary, "signal_type": "sell_flow_confirmation"},
            )

        if signal:
            logger.info(
                f"CumulativeDelta {symbol}: imbalance={imbalance:.2%} "
                f"delta={session_delta:.0f} vwap={vwap:.2f} "
                f"divergence={divergence} conf={signal.confidence:.2f}"
            )

        return signal
