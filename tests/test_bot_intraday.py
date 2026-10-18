"""The live bot's intraday controls: operator pause/flatten/resume, kill
switch, trade caps, the minute P&L log and exchange-held stops."""
from __future__ import annotations
import asyncio
import json
from types import SimpleNamespace

import pandas as pd

from strategies.base import SignalType
from utils.bot_control import write_control
from tests.test_bot_position_safety import _FakeBot, _at, _open, _signal


def _ctl(bot) -> "Path":
    return bot._control.path


def _tick(bot, price: float = 100.0, symbol: str = "RELIANCE"):
    asyncio.run(bot._on_tick({"symbol": symbol, "close": price}))


def _with_signal(bot, side=SignalType.BUY, fill=True):
    """Every tick produces one signal; the executor fills it if fill=True."""
    bot._df_cache["RELIANCE"] = pd.DataFrame({"close": range(100)})
    bot.meta_engine = SimpleNamespace(
        generate_signals=lambda symbol, d: [_signal("RELIANCE", side)],
        best_signal=lambda sigs: sigs[0])

    async def execute(signal):
        bot.executor.executed.append(signal)
        if not fill:
            return None
        bot.risk_manager.open_position(signal, 10)
        return SimpleNamespace(status="complete", filled_qty=10, quantity=10, avg_price=signal.price)
    bot.executor.execute_signal = execute


def _kinds(bot) -> list[str]:
    return [e["kind"] for e in bot._events]


# ── Operator controls ────────────────────────────────────────────────────────

def test_pause_blocks_entries_and_logs_once(monkeypatch):
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    _with_signal(bot, fill=False)
    write_control("pause", _ctl(bot))

    _tick(bot); _tick(bot)

    assert bot.executor.executed == []
    assert _kinds(bot).count("block") == 1          # not once per tick
    assert bot.guard.paused

    write_control("resume", _ctl(bot))
    _tick(bot)
    assert len(bot.executor.executed) == 1


def test_flatten_request_runs_exactly_once(monkeypatch):
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    _open(bot, "RELIANCE"); _open(bot, "TCS", SignalType.SELL)
    write_control("flatten", _ctl(bot))

    _tick(bot)
    assert bot.risk_manager.open_count == 0
    assert sorted(bot.executor.closed) == [("RELIANCE", "operator_flatten"), ("TCS", "operator_flatten")]

    _open(bot, "INFY")
    _tick(bot)                                     # same flatten_id: not repeated
    assert bot.risk_manager.open_count == 1


def test_resume_clears_a_halt(monkeypatch):
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    bot.guard.new_day(pd.Timestamp("2026-10-09").date())
    bot.guard.halted, bot.guard.halt_reason = True, "test"
    write_control("resume", _ctl(bot))
    _tick(bot)
    assert not bot.guard.halted


# ── Kill switch and caps ─────────────────────────────────────────────────────

def test_kill_switch_flattens_and_halts(monkeypatch):
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    _tick(bot)
    _open(bot, "TCS")
    bot.risk_manager.daily_pnl = -0.06 * bot.risk_manager.initial_capital

    _tick(bot)

    assert bot.risk_manager.open_count == 0
    assert ("TCS", "kill_switch") in bot.executor.closed
    assert bot.guard.halted and "halt" in _kinds(bot)


def test_kill_switch_counts_unrealised_loss(monkeypatch):
    bot = _FakeBot()
    bot.guard.max_daily_loss_pct = 0.001            # ₹500 on ₹5 lakh
    _at(monkeypatch, 11, 0)
    _open(bot, "RELIANCE")                          # 10 @ 100, stop 98
    bot.risk_manager.positions["RELIANCE"][0].stop_loss = 0.01
    _tick(bot, 40.0)                                # -₹600 unrealised
    assert bot.guard.halted and bot.risk_manager.open_count == 0


def test_filled_entries_count_against_the_daily_cap(monkeypatch):
    bot = _FakeBot()
    bot.guard.max_trades_per_symbol = 1
    _at(monkeypatch, 11, 0)
    _with_signal(bot)

    _tick(bot)
    assert bot.guard.trades_today == 1 and "entry" in _kinds(bot)
    bot.risk_manager.close_position(bot.risk_manager.positions["RELIANCE"][0], 100.0, "manual")
    _tick(bot)
    assert len(bot.executor.executed) == 1          # second entry blocked by the cap


def test_stop_out_starts_a_cooldown(monkeypatch):
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    _open(bot, "TCS")                               # stop at 98
    _tick(bot, 97.0, "TCS")
    assert ("TCS", "stop_loss") in bot.executor.closed
    assert "TCS" in bot.guard.cooldown_until


def test_entry_window_blocks_mis_entries(monkeypatch):
    bot = _FakeBot()
    bot.guard.entry_start, bot.guard.entry_end = pd.Timestamp("09:30").time(), pd.Timestamp("14:45").time()
    _with_signal(bot, fill=False)
    _at(monkeypatch, 14, 50)
    _tick(bot)
    assert bot.executor.executed == []
    assert "entry window" in bot._events[-1]["message"]


# ── P&L log ─────────────────────────────────────────────────────────────────

def test_pnl_curve_gets_one_row_per_minute(monkeypatch):
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    _open(bot, "RELIANCE")
    _tick(bot, 101.0); _tick(bot, 101.5)
    _at(monkeypatch, 11, 1)
    _tick(bot, 102.0)
    rows = [json.loads(l) for l in bot._pnl_log_file.read_text().splitlines()]
    assert [r["ts"][11:16] for r in rows] == ["11:00", "11:01"]
    assert rows[0]["unrealised"] == 10.0 and rows[1]["total"] == 20.0
    assert rows[1]["open_positions"] == 1


# ── Exchange-held stops ─────────────────────────────────────────────────────

class _StopExecutor:
    def __init__(self, status: str, cancel_ok: bool = True):
        self.status, self.cancel_ok = status, cancel_ok
        self.cancelled = 0

    async def exchange_stop_status(self, pos):
        return {"status": self.status, "avg_price": 97.9, "filled_qty": 10}

    async def cancel_exchange_stop(self, pos):
        self.cancelled += 1
        if self.cancel_ok:
            pos.stop_order_id = ""
        return self.cancel_ok


def _live_with_stop(status: str, cancel_ok: bool = True):
    bot = _FakeBot(mode="live")
    bot._exchange_stops = True
    pos = _open(bot, "RELIANCE")
    pos.stop_order_id = "STOP1"
    stops = _StopExecutor(status, cancel_ok)
    bot.executor.exchange_stop_status = stops.exchange_stop_status
    bot.executor.cancel_exchange_stop = stops.cancel_exchange_stop
    return bot, pos, stops


def test_filled_exchange_stop_books_the_exit_without_a_second_order(monkeypatch):
    _at(monkeypatch, 11, 0)
    bot, pos, stops = _live_with_stop("complete")
    asyncio.run(bot._close_tracked(pos, 98.0, "stop_loss"))
    assert bot.executor.closed == [] and stops.cancelled == 0
    assert bot.risk_manager.open_count == 0
    assert round(pos.pnl, 2) == -21.0               # booked at the stop fill, 97.9
    assert "RELIANCE" in bot.guard.cooldown_until


def test_open_exchange_stop_is_cancelled_before_closing(monkeypatch):
    _at(monkeypatch, 11, 0)
    bot, pos, stops = _live_with_stop("trigger pending")
    asyncio.run(bot._close_tracked(pos, 105.0, "take_profit"))
    assert stops.cancelled == 1
    assert bot.executor.closed == [("RELIANCE", "take_profit")]


def test_failed_cancel_sends_no_close_order(monkeypatch):
    _at(monkeypatch, 11, 0)
    bot, pos, stops = _live_with_stop("open", cancel_ok=False)
    asyncio.run(bot._close_tracked(pos, 105.0, "take_profit"))
    assert bot.executor.closed == []
    assert bot.risk_manager.open_count == 1
    assert bot._events[-1]["kind"] == "error"


# ── No shorts in delivery ───────────────────────────────────────────────────

def test_cnc_sell_closes_a_long_but_never_opens_a_short(monkeypatch):
    bot = _FakeBot(product="CNC")
    _at(monkeypatch, 11, 0)
    _with_signal(bot, side=SignalType.SELL)
    _open(bot, "RELIANCE")                          # long

    _tick(bot)                                      # SELL closes the long, stays flat
    assert ("RELIANCE", "signal_reversal") in bot.executor.closed
    assert bot.risk_manager.open_count == 0

    _tick(bot)                                      # flat: SELL must not open a short
    assert bot.executor.executed == []
    assert bot.risk_manager.open_count == 0
    assert "no short entries on CNC" in bot._events[-1]["message"]


def test_mis_sell_opens_an_intraday_short(monkeypatch):
    bot = _FakeBot(product="MIS")
    _at(monkeypatch, 11, 0)
    _with_signal(bot, side=SignalType.SELL)
    _tick(bot)
    assert len(bot.executor.executed) == 1
    assert bot.risk_manager.positions["RELIANCE"][0].direction == -1


# ── Strategy limits and sector cap in the bot ───────────────────────────────

def test_losing_strategy_is_switched_off_and_its_signals_blocked(monkeypatch):
    bot = _FakeBot()
    bot.guard.strategy_max_consecutive_losses = 2
    _at(monkeypatch, 11, 0)
    for sym in ("TCS", "INFY"):
        _open(bot, sym)
        _tick(bot, 97.0, sym)                               # stop-out, strategy "test"
    assert "test" in bot.guard.strategies_off
    assert any("Strategy test switched off" in e["message"] for e in bot._events)

    _with_signal(bot, fill=False)
    _tick(bot)
    assert bot.executor.executed == []
    assert "strategy test off for the day" in bot._events[-1]["message"]


def test_full_sector_blocks_entry(monkeypatch):
    bot = _FakeBot()
    _at(monkeypatch, 11, 0)
    bot.risk_manager.cfg["max_sector_exposure"] = 0.30
    held = _signal("HDFCBANK", SignalType.BUY, price=1500.0)
    bot.risk_manager.open_position(held, 100)               # ₹1.5 lakh = 30 % of ₹5 lakh
    _with_signal(bot, fill=False)                           # RELIANCE: Energy, allowed
    _tick(bot)
    assert len(bot.executor.executed) == 1

    bot.executor.executed.clear()
    bot._df_cache["ICICIBANK"] = bot._df_cache["RELIANCE"]
    bot.meta_engine.generate_signals = lambda symbol, d: [_signal("ICICIBANK", SignalType.BUY)]
    _tick(bot, symbol="ICICIBANK")
    assert bot.executor.executed == []
    assert "sector Banking at its 30% exposure cap" in bot._events[-1]["message"]
