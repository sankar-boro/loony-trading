"""Strategy parameters (strategies.params), setup-based confidence and
strategy-specific exits (BaseStrategy.should_exit)."""
from __future__ import annotations
import asyncio

import numpy as np
import pandas as pd
import pytest

from backtester import Backtester
from main import _bars_since
from strategies.base import BaseStrategy, Signal, SignalType
from strategies.mean_reversion.zscore_reversion import ZscoreReversionStrategy
from strategies.meta_engine import MetaStrategyEngine
from strategies.momentum.rsi_momentum import RsiMomentumStrategy
from strategies.trend.donchian_breakout import DonchianBreakoutStrategy
from strategies.trend.ema_crossover import EmaCrossoverStrategy


def _df(close, volume=None, start="2026-01-01") -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    idx = pd.date_range(start, periods=len(close), freq="D")
    vol = np.full(len(close), 1000.0) if volume is None else np.asarray(volume, dtype=float)
    return pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                         "close": close, "volume": vol}, index=idx)


# ── Parameters ───────────────────────────────────────────────────────────────

def test_param_resolution_order_and_casting():
    s = DonchianBreakoutStrategy({})
    assert s.params["dc_period"] == 20 and s.params["exit_period"] == 10

    legacy = DonchianBreakoutStrategy({"dc_period": 30})
    assert legacy.period == 30

    nested = DonchianBreakoutStrategy({"dc_period": 30,
                                       "strategies": {"params": {"donchian_breakout": {"dc_period": "55"}}}})
    assert nested.period == 55 and isinstance(nested.period, int)   # nested wins, cast to int


def test_params_do_not_leak_between_strategies():
    cfg = {"strategies": {"params": {"rsi_momentum": {"rsi_period": 21}}}}
    assert RsiMomentumStrategy(cfg).rsi_period == 21
    assert EmaCrossoverStrategy(cfg).params.get("rsi_period") is None


def test_atr_stop_multiples_are_parameters():
    df = _df(np.linspace(100, 120, 60))
    default = DonchianBreakoutStrategy({})
    wide = DonchianBreakoutStrategy({"strategies": {"params": {"donchian_breakout": {"atr_stop_mult": 4.0}}}})
    sl_d, _ = default._atr_stops(df, 1)
    sl_w, _ = wide._atr_stops(df, 1)
    price = df["close"].iloc[-1]
    assert (price - sl_w) == pytest.approx(2 * (price - sl_d))


# ── Confidence ───────────────────────────────────────────────────────────────

def test_scaled_confidence_bounds():
    assert BaseStrategy.scaled_confidence(-1) == 0.55
    assert BaseStrategy.scaled_confidence(0.5) == 0.7
    assert BaseStrategy.scaled_confidence(9) == 0.85


def test_bigger_breakout_with_volume_gets_higher_confidence():
    base = list(np.full(40, 100.0))
    s = DonchianBreakoutStrategy({})
    marginal = s.generate_signal(_df(base + [100.6]), "T")
    decisive = s.generate_signal(_df(base + [104.0], volume=[1000] * 40 + [4000]), "T")
    assert marginal and decisive and marginal.signal_type == SignalType.BUY
    assert decisive.confidence > marginal.confidence
    assert 0.55 <= marginal.confidence <= 0.85


# ── Exits ────────────────────────────────────────────────────────────────────

def test_time_stop_from_params():
    s = DonchianBreakoutStrategy({"strategies": {"params": {"donchian_breakout": {"max_hold_bars": 5}}}})
    df = _df(np.full(40, 100.0))
    assert s.should_exit(df, 1, 4) is None
    assert "time stop" in s.should_exit(df, 1, 5)


def test_donchian_exits_through_opposite_channel():
    s = DonchianBreakoutStrategy({})
    up = list(np.linspace(100, 120, 30))
    assert s.should_exit(_df(up), 1, 3) is None
    assert "10-bar low" in s.should_exit(_df(up + [105.0]), 1, 3)
    assert s.should_exit(_df(up + [105.0]), -1, 3) is None


def test_zscore_exits_when_reverted():
    s = ZscoreReversionStrategy({})
    rng = np.random.default_rng(0)
    flat = list(100 + rng.normal(0, 0.3, 40))
    assert "reverted" in s.should_exit(_df(flat), 1, 2)            # z near 0
    assert s.should_exit(_df(flat + [95.0]), 1, 2) is None          # still stretched


def test_rsi_momentum_exits_when_rsi_falls_back():
    s = RsiMomentumStrategy({})
    falling = list(np.linspace(120, 100, 40))
    assert "RSI back below" in s.should_exit(_df(falling), 1, 3)
    assert s.should_exit(_df(falling), -1, 3) is None


def test_ema_crossover_exits_on_opposite_cross():
    s = EmaCrossoverStrategy({})
    falling = list(np.linspace(120, 100, 40))
    assert s.should_exit(_df(falling), 1, 3) == "EMA death cross"
    assert s.should_exit(_df(falling), -1, 3) is None


# ── Wiring ───────────────────────────────────────────────────────────────────

def test_engine_strategy_lookup():
    eng = MetaStrategyEngine({"strategies": {"enabled": ["donchian_breakout"]}})
    assert isinstance(eng.strategy("donchian_breakout"), DonchianBreakoutStrategy)
    assert eng.strategy("supertrend") is None


def test_bars_since_entry():
    df = _df(np.full(10, 100.0))                                    # naive daily bars (IST)
    assert _bars_since(df, "2026-01-05T09:00:00+05:30") == 5        # 6th..10th Jan
    assert _bars_since(df, "") == 0


class _BuyThenExitAfter3(BaseStrategy):
    name = "buy_then_exit"

    def __init__(self):
        super().__init__({})
        self.fired = False

    def generate_signal(self, df, symbol):
        if self.fired:
            return None
        self.fired = True
        p = float(df["close"].iloc[-1])
        return Signal(strategy=self.name, symbol=symbol, signal_type=SignalType.BUY, price=p,
                      stop_loss=p * 0.5, take_profit=p * 2, confidence=1.0)

    def should_exit(self, df, direction, bars_held):
        return "done" if bars_held >= 3 else None


def test_backtester_uses_strategy_exit():
    cfg = {"risk": {"trailing_stop_pct": 0}, "execution": {"slippage_pct": 0, "commission_delivery": 0},
           "data": {"warmup_bars": 3}}
    r = Backtester(cfg, initial_capital=100_000).run(_df(np.full(12, 100.0)), "T",
                                                     strategy=_BuyThenExitAfter3())
    [t] = r.trades
    assert t.reason == "strategy_exit" and t.exit_bar - t.entry_bar == 3


def test_bot_closes_on_strategy_exit(monkeypatch):
    from tests.test_bot_position_safety import _FakeBot, _at, _open
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    pos = _open(bot, "RELIANCE")
    strat = _BuyThenExitAfter3()
    strat.name = pos.strategy
    bot.meta_engine.strategy = lambda name: strat if name == strat.name else None
    monkeypatch.setattr("main._bars_since", lambda df, t: 3)
    closed = asyncio.run(bot._check_strategy_exits("RELIANCE", _df(np.full(70, 100.0)), 101.0))
    assert closed and bot.executor.closed == [("RELIANCE", "strategy_exit (done)")]
