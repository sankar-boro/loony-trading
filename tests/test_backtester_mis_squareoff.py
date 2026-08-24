"""Tests for MIS auto-squareoff simulation in the backtester
(docs/intraday_gaps.md §3/§7 item 3): an intraday-product (MIS) backtest
must force-close any open position at 3:14 PM IST, matching what the
live bot's should_squareoff_mis() actually does — and must not open a
fresh position that late either. A CNC (delivery) backtest must not be
affected at all."""
from __future__ import annotations
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from backtester import Backtester
from strategies.base import BaseStrategy, Signal, SignalType

CFG = {
    "risk": {"max_risk_per_trade": 0.01},
    "execution": {"slippage_pct": 0.0, "commission_intraday": 0.0, "commission_delivery": 0.0},
    "data": {"warmup_bars": 5},
}


def _one_session_df(start="09:15", periods=75, freq="5min", price=100.0) -> pd.DataFrame:
    """One full NSE session (09:15-15:30, 5-min bars) at a flat price,
    tz-naive (treated as IST per this project's convention) — no natural
    price movement, so a position only ever exits via an explicit
    stop/target hit or the MIS squareoff being tested."""
    idx = pd.date_range(f"2026-08-24 {start}", periods=periods, freq=freq)
    close = np.full(periods, price)
    return pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": np.full(periods, 1000.0),
    }, index=idx)


class _BuyOnceWideStops(BaseStrategy):
    """Enters exactly one long position on its first call, with stop/
    target far outside the flat test price range so nothing but MIS
    squareoff (or end-of-data) can close it."""
    name = "buy_once_wide_stops"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._fired = False

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if self._fired:
            return None
        self._fired = True
        price = float(df["close"].iloc[-1])
        return Signal(
            strategy=self.name, symbol=symbol, signal_type=SignalType.BUY,
            price=price, stop_loss=price * 0.5, take_profit=price * 2.0,
            confidence=1.0,
        )


class _AlwaysBuyWideStops(BaseStrategy):
    """Tries to enter on every single call — used to verify no fresh MIS
    entry happens after the squareoff cutoff."""
    name = "always_buy_wide_stops"

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        price = float(df["close"].iloc[-1])
        return Signal(
            strategy=self.name, symbol=symbol, signal_type=SignalType.BUY,
            price=price, stop_loss=price * 0.5, take_profit=price * 2.0,
            confidence=1.0,
        )


def test_mis_position_force_closed_at_314pm_ist():
    df = _one_session_df()
    bt = Backtester(CFG, initial_capital=100_000, product="MIS")
    result = bt.run(df, "RELIANCE", strategy=_BuyOnceWideStops({}))

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.reason == "mis_squareoff"

    exit_ts = df.index[trade.exit_bar]
    assert exit_ts.time() >= pd.Timestamp("15:14").time()


def test_cnc_position_not_force_closed_rides_to_end_of_data():
    df = _one_session_df()
    bt = Backtester(CFG, initial_capital=100_000, product="CNC")
    result = bt.run(df, "RELIANCE", strategy=_BuyOnceWideStops({}))

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.reason == "end_of_data"  # never force-closed for a delivery product


def test_mis_no_fresh_entry_opened_after_squareoff_cutoff():
    # Every bar tries to enter — with wide stops nothing triggers a
    # natural exit, so any position opened would still be open (and get
    # force-closed) at the next bar. If a "fresh entry after cutoff" bug
    # existed, we'd see entry_bar timestamps at/after 15:14 IST.
    df = _one_session_df()
    bt = Backtester(CFG, initial_capital=100_000, product="MIS")
    result = bt.run(df, "RELIANCE", strategy=_AlwaysBuyWideStops({}))

    for trade in result.trades:
        entry_ts = df.index[trade.entry_bar]
        assert entry_ts.time() < pd.Timestamp("15:14").time(), (
            f"MIS entry opened at {entry_ts.time()}, at/after the squareoff cutoff"
        )


def test_mis_squareoff_only_applies_with_datetime_index():
    # A plain RangeIndex (no timestamps) must not crash or misbehave —
    # mis_squareoff_now can never be determined, so it's simply never
    # triggered, same as before this fix for non-timestamped data.
    idx_free_df = _one_session_df().reset_index(drop=True)
    bt = Backtester(CFG, initial_capital=100_000, product="MIS")
    result = bt.run(idx_free_df, "RELIANCE", strategy=_BuyOnceWideStops({}))

    assert len(result.trades) == 1
    assert result.trades[0].reason == "end_of_data"
