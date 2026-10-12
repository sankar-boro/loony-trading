"""Realistic exits in the backtester: stops and targets are checked against
each bar's high/low, gaps fill at the open, the stop trails like the live
RiskManager's, and every exit (end_of_data included) pays costs."""
from __future__ import annotations
from typing import Optional

import pandas as pd
import pytest

from backtester import Backtester
from strategies.base import BaseStrategy, Signal, SignalType

WARMUP = 3


def _cfg(trailing: float = 0.0, slippage: float = 0.0, commission: float = 0.0) -> dict:
    return {
        "risk": {"max_risk_per_trade": 0.01, "trailing_stop_pct": trailing},
        "execution": {"slippage_pct": slippage, "commission_delivery": commission},
        "data": {"warmup_bars": WARMUP},
    }


class _BuyOnce(BaseStrategy):
    """Goes long once at the close, stop 95 / target 110 (for an entry at 100)."""
    name = "buy_once"

    def __init__(self, side: SignalType = SignalType.BUY):
        super().__init__({})
        self.side, self._fired = side, False

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if self._fired:
            return None
        self._fired = True
        p = float(df["close"].iloc[-1])
        long = self.side == SignalType.BUY
        return Signal(strategy=self.name, symbol=symbol, signal_type=self.side, price=p,
                      stop_loss=p * (0.95 if long else 1.05),
                      take_profit=p * (1.10 if long else 0.90), confidence=1.0)


def _df(bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Flat 100 warm-up bars, then the given (open, high, low, close) bars.
    The entry happens at the close of bar WARMUP (the first flat bar after
    warm-up), so the scripted bars start right after it."""
    flat = [(100.0, 100.0, 100.0, 100.0)] * (WARMUP + 1)
    rows = flat + bars
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=1000.0)


def _run(bars, side=SignalType.BUY, **cfg):
    bt = Backtester(_cfg(**cfg), initial_capital=100_000)
    return bt.run(_df(bars), "TEST", strategy=_BuyOnce(side))


def test_wick_through_the_stop_exits_at_the_stop_even_if_close_recovers():
    r = _run([(100, 101, 94, 99.5)])
    [t] = r.trades
    assert t.reason == "stop_loss" and t.exit_price == pytest.approx(95.0)


def test_wick_through_the_target_exits_at_the_target():
    r = _run([(100, 111, 99, 100.5)])
    [t] = r.trades
    assert t.reason == "take_profit" and t.exit_price == pytest.approx(110.0)


def test_bar_touching_both_assumes_the_stop_came_first():
    [t] = _run([(100, 112, 93, 100)]).trades
    assert t.reason == "stop_loss"


def test_gap_below_the_stop_fills_at_the_open():
    [t] = _run([(90, 91, 88, 90)]).trades
    assert t.reason == "stop_loss" and t.exit_price == pytest.approx(90.0)


def test_gap_above_the_target_fills_at_the_open():
    [t] = _run([(115, 116, 114, 115)]).trades
    assert t.reason == "take_profit" and t.exit_price == pytest.approx(115.0)


def test_short_side_mirrors():
    [t] = _run([(100, 106, 99, 100)], side=SignalType.SELL).trades
    assert t.reason == "stop_loss" and t.exit_price == pytest.approx(105.0)
    [t] = _run([(100, 101, 89, 100)], side=SignalType.SELL).trades
    assert t.reason == "take_profit" and t.exit_price == pytest.approx(90.0)


def test_trailing_stop_locks_in_a_gain():
    # Rally to 108 (stop trails to 108 * 0.98 = 105.84), then fall back
    r = _run([(100, 108, 100, 107), (107, 107, 104, 104)], trailing=0.02)
    [t] = r.trades
    assert t.reason == "stop_loss" and t.exit_price == pytest.approx(105.84)
    assert t.pnl > 0


def test_trailing_stop_never_loosens():
    r = _run([(100, 101, 99, 100), (100, 100, 96, 97)], trailing=0.10)
    assert r.trades[0].reason == "end_of_data"       # stop stayed at 95


def test_trailing_off_with_zero():
    r = _run([(100, 108, 100, 107), (107, 107, 104, 104)], trailing=0.0)
    assert r.trades[0].reason == "end_of_data"


def test_end_of_data_pays_slippage_and_costs_and_reaches_equity():
    r = _run([(100, 101, 99, 100)], slippage=0.001, commission=0.002)
    [t] = r.trades
    assert t.reason == "end_of_data"
    assert t.exit_price == pytest.approx(100 * 0.999)       # sold into the bid
    gross = (t.exit_price - t.entry_price) * t.size
    assert t.pnl == pytest.approx(gross - 0.001 * t.exit_price * t.size)
    entry_cost = 0.001 * t.entry_price * t.size
    assert r.equity_curve[-1] == pytest.approx(100_000 - entry_cost + t.pnl)


def test_close_only_data_still_works():
    df = _df([(100, 101, 94, 94)])[["close"]]
    [t] = Backtester(_cfg(), initial_capital=100_000).run(df, "TEST", strategy=_BuyOnce()).trades
    assert t.reason == "stop_loss" and t.exit_price == pytest.approx(94.0)
