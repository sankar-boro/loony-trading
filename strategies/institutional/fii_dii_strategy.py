"""
FII/DII Institutional Flow Strategy.

Core insight: FII (Foreign Institutional Investors) are the single largest
driver of Nifty direction. When FII is a net buyer for 3+ consecutive days,
the market has a strong upward bias and vice versa.

Additional filters:
- DII often counters FII on down days (buying when FII sells) — combined signal
  is more reliable than FII alone
- Delivery % confirms genuine institutional interest vs intraday noise
- F&O ban list prevents illegal new positions

Signal logic:
- FII net buy > ₹1000 Cr for 3+ days → BULLISH → buy Nifty/stocks on dips
- FII net sell > ₹1000 Cr for 3+ days → BEARISH → sell rallies / buy puts
- DII aggressively buying when FII sells → stabilisation → reduce short exposure
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from strategies.base import BaseStrategy, Signal, SignalType
from data_engine.nse_data import (
    get_fii_sentiment,
    fetch_fii_dii_activity,
    is_in_fo_ban,
    get_delivery_pct,
    has_upcoming_corporate_action,
)
from utils.logger import get_logger

logger = get_logger("fii_dii_strategy")


class FIIDIIStrategy(BaseStrategy):
    """
    Trade in the direction of institutional money flow.

    This is NOT a pure alpha strategy — it's a macro bias filter.
    Use it to:
    1. Tilt position sizing toward FII direction
    2. Block counter-FII trades in high-conviction flow periods
    3. Add long bias on stocks with high delivery %
    """
    name = "fii_dii"
    category = "institutional"
    preferred_regimes = ["all"]

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        icfg = cfg.get("institutional", {}).get("fii_dii", {})
        self.fii_threshold_cr       = icfg.get("fii_threshold_cr", 1000.0)     # ₹1000 Cr
        self.consecutive_days       = icfg.get("consecutive_days", 3)
        self.delivery_min_pct       = icfg.get("delivery_min_pct", 45.0)
        self.size_boost_bullish     = icfg.get("size_boost_bullish", 1.25)      # 25% larger
        self.size_reduce_bearish    = icfg.get("size_reduce_bearish", 0.75)     # 25% smaller
        self.block_counter_strong   = icfg.get("block_counter_strong", True)   # block signals against flow

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """
        Generates directional bias signals for index instruments (Nifty/BankNifty).
        For individual stocks, use get_size_multiplier() instead.
        """
        if not self.validate_df(df, 5):
            return None

        # Only trade index instruments directly
        is_index = any(x in symbol.upper() for x in ["NIFTY", "BANKNIFTY", "SENSEX"])
        if not is_index:
            return None

        sentiment = get_fii_sentiment(lookback_days=self.consecutive_days)
        if sentiment["signal"] == "NEUTRAL":
            return None

        fii_daily_avg = abs(sentiment["fii_daily_avg"])
        if fii_daily_avg < self.fii_threshold_cr / self.consecutive_days:
            return None

        spot = df["close"].iloc[-1]
        signal_type = SignalType.BUY if sentiment["signal"] == "BULLISH" else SignalType.SELL

        sl_pct  = 0.008  # 0.8% stop
        tp_pct  = 0.015  # 1.5% target (2:1 RR)
        if signal_type == SignalType.BUY:
            sl = spot * (1 - sl_pct)
            tp = spot * (1 + tp_pct)
        else:
            sl = spot * (1 + sl_pct)
            tp = spot * (1 - tp_pct)

        confidence = min(0.55 + fii_daily_avg / 5000.0, 0.85)

        logger.info(
            f"FII/DII {symbol}: {sentiment['signal']} "
            f"FII_avg=₹{fii_daily_avg:.0f}Cr DII=₹{sentiment['dii_net']:.0f}Cr "
            f"conf={confidence:.2f}"
        )

        return Signal(
            strategy=self.name,
            symbol=symbol,
            signal_type=signal_type,
            price=spot,
            stop_loss=sl,
            take_profit=tp,
            confidence=confidence,
            metadata={
                "fii_net_cr": round(sentiment["fii_net"], 2),
                "dii_net_cr": round(sentiment["dii_net"], 2),
                "combined_net_cr": round(sentiment["combined_net"], 2),
                "fii_daily_avg_cr": round(fii_daily_avg, 2),
                "sentiment": sentiment["signal"],
                "lookback_days": self.consecutive_days,
            },
        )

    def get_size_multiplier(self, symbol: str) -> float:
        """
        Returns position size multiplier based on FII sentiment.
        1.0 = normal, 1.25 = bullish boost, 0.75 = bearish reduction.
        Used by the executor to scale position sizes.
        """
        if is_in_fo_ban(symbol):
            logger.warning(f"{symbol} is in F&O ban — blocking trade")
            return 0.0

        action = has_upcoming_corporate_action(symbol, days=3)
        if action:
            logger.warning(f"{symbol} has upcoming {action['action']} on {action['ex_date']} — reducing size")
            return 0.5

        sentiment = get_fii_sentiment(lookback_days=3)
        if sentiment["signal"] == "BULLISH":
            return self.size_boost_bullish
        if sentiment["signal"] == "BEARISH":
            return self.size_reduce_bearish
        return 1.0

    def should_block_signal(self, signal: Signal) -> bool:
        """
        Returns True if the signal should be blocked because it goes
        strongly against institutional flow.
        """
        if not self.block_counter_strong:
            return False

        sentiment = get_fii_sentiment(lookback_days=self.consecutive_days)
        fii_net = sentiment["fii_net"]

        # Block BUY signals when FII is aggressively selling
        if signal.signal_type == SignalType.BUY and fii_net < -(self.fii_threshold_cr * 2):
            logger.info(f"Blocking BUY {signal.symbol} — FII selling ₹{abs(fii_net):.0f}Cr")
            return True

        # Block SELL signals when FII is aggressively buying
        if signal.signal_type == SignalType.SELL and fii_net > self.fii_threshold_cr * 2:
            logger.info(f"Blocking SELL {signal.symbol} — FII buying ₹{fii_net:.0f}Cr")
            return True

        return False

    def get_stock_delivery_signal(self, symbol: str) -> Optional[dict]:
        """
        Returns a delivery-based signal for individual stocks.
        High delivery % + FII bullish = strong accumulation.
        """
        delivery_pct = get_delivery_pct(symbol)
        if delivery_pct is None:
            return None

        sentiment = get_fii_sentiment(lookback_days=3)

        signal_strength = "WEAK"
        if delivery_pct >= self.delivery_min_pct and sentiment["signal"] == "BULLISH":
            signal_strength = "STRONG_BUY"
        elif delivery_pct >= self.delivery_min_pct:
            signal_strength = "ACCUMULATION"
        elif delivery_pct < 20.0 and sentiment["signal"] == "BEARISH":
            signal_strength = "DISTRIBUTION"

        return {
            "symbol": symbol,
            "delivery_pct": round(delivery_pct, 1),
            "fii_sentiment": sentiment["signal"],
            "signal_strength": signal_strength,
        }
