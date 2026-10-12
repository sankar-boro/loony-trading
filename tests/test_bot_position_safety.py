"""Regression tests for the live loop's position-safety fixes in main.py
(docs/appendix/status.md §4): MIS squareoff in paper and live mode, no new intraday
entries after the cut-off, and one position per symbol.

Like test_bot_live_refresh.py, this runs the real UpstoxTradingBot methods
against a lightweight stand-in instead of constructing a full bot (which
needs Upstox credentials and the whole strategy/ML stack)."""
from __future__ import annotations
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

import utils.timeutils as timeutils
from main import UpstoxTradingBot
from risk_manager.risk_manager import RiskManager
from strategies.base import Signal, SignalType


class _Executor:
    def __init__(self, risk_manager: RiskManager, product: str = "MIS"):
        self.rm = risk_manager
        self._default_product = SimpleNamespace(value=product)
        self.closed: list[tuple[str, str]] = []
        self.executed: list[Signal] = []
        self.broker_squareoffs = 0

    async def close_position(self, pos, price, reason):
        self.rm.close_position(pos, price, reason)
        self.closed.append((pos.symbol, reason))
        return SimpleNamespace(avg_price=price)

    async def squareoff_all_mis(self):
        self.broker_squareoffs += 1
        return []

    async def execute_signal(self, signal):
        self.executed.append(signal)
        return None


class _Notifier:
    async def send(self, msg):
        pass


class _FakeBot:
    _is_intraday_product = UpstoxTradingBot._is_intraday_product
    _close_tracked = UpstoxTradingBot._close_tracked
    _squareoff_mis = UpstoxTradingBot._squareoff_mis
    _handle_existing_position = UpstoxTradingBot._handle_existing_position
    _on_tick = UpstoxTradingBot._on_tick
    _process_tick = UpstoxTradingBot._process_tick
    _is_sane_tick = UpstoxTradingBot._is_sane_tick

    def _save_state(self, force=False):
        pass

    def __init__(self, mode: str = "paper", product: str = "MIS"):
        self.mode = mode
        self.risk_manager = RiskManager({"risk": {}}, 500_000)
        self.executor = _Executor(self.risk_manager, product)
        self.notifier = _Notifier()
        self.trade_logger = SimpleNamespace(log_position_close=lambda *a, **k: None)
        self.portfolio = SimpleNamespace(
            record_trade=lambda *a, **k: None,
            update_price=lambda *a, **k: None,
            is_correlated=lambda *a, **k: False,
        )
        self.meta_engine = SimpleNamespace(generate_signals=lambda symbol, df: [])
        self.intraday_tf = "1m"
        self._df_cache = {}
        self._df_cache_base = {}
        self._last_price = {}
        self._mis_squareoff_date = None
        self._session_date = None
        self._suspect_ticks = {}
        self.cfg = {}


def _signal(symbol: str, side: SignalType, price: float = 100.0) -> Signal:
    stop = price - 2 if side == SignalType.BUY else price + 2
    target = price + 4 if side == SignalType.BUY else price - 4
    return Signal(symbol=symbol, signal_type=side, confidence=0.9, price=price,
                  stop_loss=stop, take_profit=target, strategy="test")


def _open(bot: _FakeBot, symbol: str, side: SignalType = SignalType.BUY):
    return bot.risk_manager.open_position(_signal(symbol, side), 10)


def _at(monkeypatch, hour: int, minute: int):
    monkeypatch.setattr(timeutils, "now_ist",
                        lambda: datetime(2026, 10, 9, hour, minute, tzinfo=timeutils.IST))


# ── MIS squareoff ────────────────────────────────────────────────────────────

def test_paper_squareoff_closes_tracked_positions():
    bot = _FakeBot(mode="paper")
    _open(bot, "RELIANCE")
    _open(bot, "TCS", SignalType.SELL)

    asyncio.run(bot._squareoff_mis())

    assert bot.risk_manager.open_count == 0
    assert sorted(bot.executor.closed) == [("RELIANCE", "mis_squareoff"), ("TCS", "mis_squareoff")]
    assert bot.executor.broker_squareoffs == 0


def test_live_squareoff_drops_positions_without_second_order():
    bot = _FakeBot(mode="live")
    _open(bot, "RELIANCE")

    asyncio.run(bot._squareoff_mis())

    assert bot.executor.broker_squareoffs == 1
    assert bot.executor.closed == []          # broker closed it; no opposite order
    assert bot.risk_manager.open_count == 0   # and it is gone from the book


def test_squareoff_leaves_delivery_positions_alone():
    bot = _FakeBot(mode="paper", product="CNC")
    _open(bot, "RELIANCE")

    asyncio.run(bot._squareoff_mis())

    assert bot.risk_manager.open_count == 1


def test_squareoff_fires_once_per_day_from_tick_loop(monkeypatch):
    bot = _FakeBot(mode="live")
    _at(monkeypatch, 15, 20)
    tick = {"symbol": "RELIANCE", "close": 101.0}

    asyncio.run(bot._on_tick(tick))
    asyncio.run(bot._on_tick(tick))

    assert bot.executor.broker_squareoffs == 1


def test_no_new_intraday_entries_after_cutoff(monkeypatch):
    bot = _FakeBot(mode="paper")
    df = pd.DataFrame({"close": range(100)})
    bot._df_cache["RELIANCE"] = df
    bot.meta_engine = SimpleNamespace(
        generate_signals=lambda symbol, d: [_signal("RELIANCE", SignalType.BUY)],
        best_signal=lambda sigs: max(sigs, key=lambda s: s.confidence))
    tick = {"symbol": "RELIANCE", "close": 100.0}

    _at(monkeypatch, 15, 20)
    asyncio.run(bot._on_tick(tick))
    assert bot.executor.executed == []

    _at(monkeypatch, 11, 0)
    bot._mis_squareoff_date = None
    asyncio.run(bot._on_tick(tick))
    assert len(bot.executor.executed) == 1


# ── One position per symbol ─────────────────────────────────────────────────

def test_same_direction_signal_is_ignored():
    bot = _FakeBot()
    _open(bot, "RELIANCE", SignalType.BUY)

    ok = asyncio.run(bot._handle_existing_position(_signal("RELIANCE", SignalType.BUY), 101.0))

    assert ok is False
    assert bot.risk_manager.open_count == 1
    assert bot.executor.closed == []


def test_opposite_signal_closes_and_stays_flat():
    bot = _FakeBot()
    _open(bot, "RELIANCE", SignalType.BUY)

    ok = asyncio.run(bot._handle_existing_position(_signal("RELIANCE", SignalType.SELL), 99.0))

    assert ok is False
    assert bot.risk_manager.open_count == 0
    assert bot.executor.closed == [("RELIANCE", "signal_reversal")]


def test_flat_symbol_allows_entry():
    bot = _FakeBot()
    ok = asyncio.run(bot._handle_existing_position(_signal("RELIANCE", SignalType.BUY), 100.0))
    assert ok is True


def test_risk_manager_rejects_second_position_in_symbol():
    rm = RiskManager({"risk": {}}, 500_000)
    rm.open_position(_signal("RELIANCE", SignalType.BUY), 10)
    assert rm.validate_signal(_signal("RELIANCE", SignalType.BUY)) is False
    assert rm.validate_signal(_signal("RELIANCE", SignalType.SELL)) is False
    assert rm.validate_signal(_signal("TCS", SignalType.BUY)) is True


# ── Tick sanity check ───────────────────────────────────────────────────────

def test_zero_and_spike_ticks_are_dropped():
    bot = _FakeBot()
    assert bot._is_sane_tick("RELIANCE", 0) is False
    assert bot._is_sane_tick("RELIANCE", 100.0) is True
    bot._last_price["RELIANCE"] = 100.0
    assert bot._is_sane_tick("RELIANCE", 119.0) is True     # within 20%
    assert bot._is_sane_tick("RELIANCE", 1000.0) is False   # 10x spike


def test_spike_tick_never_reaches_stop_check(monkeypatch):
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    _open(bot, "RELIANCE")                     # long, stop at 98
    bot._last_price["RELIANCE"] = 100.0

    asyncio.run(bot._on_tick({"symbol": "RELIANCE", "close": 1.0}))   # corrupt tick

    assert bot.risk_manager.open_count == 1
    assert bot._last_price["RELIANCE"] == 100.0


def test_consistent_new_level_is_accepted_after_three_ticks():
    bot = _FakeBot()
    bot._last_price["RELIANCE"] = 100.0
    assert bot._is_sane_tick("RELIANCE", 50.0) is False
    assert bot._is_sane_tick("RELIANCE", 50.2) is False
    assert bot._is_sane_tick("RELIANCE", 50.1) is True     # e.g. a 1:1 bonus re-basing


def test_inconsistent_bad_ticks_keep_being_dropped():
    bot = _FakeBot()
    bot._last_price["RELIANCE"] = 100.0
    for p in (50.0, 300.0, 10.0, 500.0):
        assert bot._is_sane_tick("RELIANCE", p) is False


def test_daily_pnl_resets_on_a_new_trading_day(monkeypatch):
    bot = _FakeBot()
    tick = {"symbol": "RELIANCE", "close": 100.0}
    _at(monkeypatch, 11, 0)
    asyncio.run(bot._on_tick(tick))
    bot.risk_manager.daily_pnl = -20_000.0          # a bad day

    asyncio.run(bot._on_tick(tick))                 # same day: kept
    assert bot.risk_manager.daily_pnl == -20_000.0

    monkeypatch.setattr(timeutils, "now_ist",
                        lambda: datetime(2026, 10, 12, 9, 20, tzinfo=timeutils.IST))
    asyncio.run(bot._on_tick(tick))                 # next trading day: reset
    assert bot.risk_manager.daily_pnl == 0.0
