"""Session-level intraday rules (risk_manager/intraday_guard.py)."""
from __future__ import annotations
from datetime import date, datetime, time

from risk_manager.intraday_guard import IntradayGuard
from utils.timeutils import IST

DAY = date(2026, 10, 12)


def _t(h: int, m: int) -> datetime:
    return datetime(2026, 10, 12, h, m, tzinfo=IST)


def _guard(**kw) -> IntradayGuard:
    g = IntradayGuard(**kw)
    g.new_day(DAY)
    return g


def test_from_config_reads_intraday_and_risk_sections():
    g = IntradayGuard.from_config({
        "risk": {"max_daily_drawdown": 0.02},
        "intraday": {"entry_start": "09:45", "entry_end": "14:30", "max_trades_per_day": 8,
                     "max_trades_per_symbol": 2, "cooldown_minutes_after_stop": 15,
                     "profit_lock_pct": 0.01, "kill_switch": {"flatten_on_daily_loss": False}},
    })
    assert (g.entry_start, g.entry_end) == (time(9, 45), time(14, 30))
    assert (g.max_trades_per_day, g.max_trades_per_symbol, g.cooldown_minutes) == (8, 2, 15)
    assert g.max_daily_loss_pct == 0.02 and g.profit_lock_pct == 0.01
    assert g.flatten_on_daily_loss is False


def test_bad_time_strings_fall_back_to_defaults():
    g = IntradayGuard.from_config({"intraday": {"entry_start": "soon", "entry_end": None}})
    assert (g.entry_start, g.entry_end) == (time(9, 30), time(14, 45))


def test_entry_window_applies_to_intraday_product_only():
    g = _guard()
    assert g.can_enter("TCS", _t(9, 20), intraday_product=True)[0] is False
    assert g.can_enter("TCS", _t(9, 20), intraday_product=False)[0] is True
    assert g.can_enter("TCS", _t(10, 0), intraday_product=True) == (True, "")
    ok, why = g.can_enter("TCS", _t(14, 50), intraday_product=True)
    assert not ok and "entry window" in why


def test_daily_and_per_symbol_caps():
    g = _guard(max_trades_per_day=3, max_trades_per_symbol=2)
    g.record_entry("TCS"); g.record_entry("TCS")
    ok, why = g.can_enter("TCS", _t(11, 0), True)
    assert not ok and "TCS trade cap" in why
    assert g.can_enter("INFY", _t(11, 0), True)[0]
    g.record_entry("INFY")
    ok, why = g.can_enter("WIPRO", _t(11, 0), True)
    assert not ok and "daily trade cap" in why


def test_cooldown_after_stop_loss_only():
    g = _guard(cooldown_minutes=30)
    g.record_exit("TCS", "take_profit", _t(11, 0))
    assert g.can_enter("TCS", _t(11, 1), True)[0]
    g.record_exit("TCS", "stop_loss", _t(11, 0))
    ok, why = g.can_enter("TCS", _t(11, 29), True)
    assert not ok and "cooling down until 11:30" in why
    assert g.can_enter("TCS", _t(11, 30), True)[0]


def test_kill_switch_halts_once():
    g = _guard(max_daily_loss_pct=0.02)
    assert g.check_day_pnl(-9_000, 500_000) is None
    assert g.check_day_pnl(-10_000, 500_000) == "kill"
    assert g.halted and "daily loss" in g.halt_reason
    assert g.check_day_pnl(-20_000, 500_000) is None      # already halted: no repeat
    ok, why = g.can_enter("TCS", _t(11, 0), True)
    assert not ok and why.startswith("halted")


def test_profit_lock_is_off_by_default_and_halts_when_set():
    assert _guard().check_day_pnl(1_000_000, 500_000) is None
    g = _guard(profit_lock_pct=0.01)
    assert g.check_day_pnl(5_000, 500_000) == "lock"
    assert g.halted


def test_pause_and_resume():
    g = _guard()
    g.paused = True
    assert g.can_enter("TCS", _t(11, 0), True) == (False, "entries paused")
    g.check_day_pnl(-1e9, 500_000)
    g.resume()
    assert not g.paused and not g.halted
    assert g.can_enter("TCS", _t(11, 0), True)[0]


def test_new_day_resets_counters_but_keeps_pause():
    g = _guard(max_daily_loss_pct=0.01)
    g.record_entry("TCS")
    g.record_exit("TCS", "stop_loss", _t(11, 0))
    g.check_day_pnl(-1e9, 500_000)
    g.paused = True
    assert g.new_day(DAY) is False
    assert g.new_day(date(2026, 10, 13)) is True
    assert g.trades_today == 0 and not g.trades_by_symbol and not g.cooldown_until
    assert not g.halted and g.paused


def test_state_round_trip_same_day_only():
    g = _guard()
    g.record_entry("TCS")
    g.record_exit("TCS", "stop_loss", _t(11, 0))
    g.check_day_pnl(-1e9, 500_000)
    state = g.to_state(_t(11, 5))
    assert state["in_entry_window"] is True and "TCS" in state["cooldowns"]

    fresh = IntradayGuard()
    fresh.restore(state, DAY)
    assert fresh.trades_today == 1 and fresh.trades_by_symbol == {"TCS": 1}
    assert fresh.halted and fresh.cooldown_until["TCS"] == _t(11, 30)

    other = IntradayGuard()
    other.restore(state, date(2026, 10, 13))
    assert other.trades_today == 0 and not other.halted


# ── Per-strategy limits ─────────────────────────────────────────────────────

def test_strategy_switched_off_after_daily_loss():
    g = _guard(strategy_max_daily_loss_pct=0.01, capital=500_000)
    assert g.record_strategy_result("orb", -3_000) is None
    reason = g.record_strategy_result("orb", -2_500)          # -5,500 ≤ -5,000
    assert reason and "lost ₹5,500" in reason
    ok, why = g.can_enter("TCS", _t(11, 0), True, strategy="orb")
    assert not ok and "strategy orb off" in why
    assert g.can_enter("TCS", _t(11, 0), True, strategy="vwap")[0]
    assert g.record_strategy_result("orb", -100) is None        # reported once


def test_strategy_switched_off_after_losing_streak():
    g = _guard(strategy_max_consecutive_losses=3, strategy_max_daily_loss_pct=0, capital=500_000)
    g.record_strategy_result("orb", -10); g.record_strategy_result("orb", -10)
    g.record_strategy_result("orb", +50)                        # streak resets
    g.record_strategy_result("orb", -10); g.record_strategy_result("orb", -10)
    assert "orb" not in g.strategies_off
    assert "3 losing trades" in g.record_strategy_result("orb", -10)


def test_strategy_limits_reset_daily_and_on_resume_and_persist():
    g = _guard(strategy_max_consecutive_losses=1, capital=500_000)
    g.record_strategy_result("orb", -10)
    assert "orb" in g.strategies_off
    restored = IntradayGuard()
    restored.restore(g.to_state(_t(11, 0)), DAY)
    assert "orb" in restored.strategies_off and restored.strategy_pnl == {"orb": -10.0}
    g.resume()
    assert not g.strategies_off
    g.record_strategy_result("orb", -10)
    g.new_day(date(2026, 10, 13))
    assert not g.strategies_off and not g.strategy_pnl


def test_strategy_limits_from_config():
    g = IntradayGuard.from_config({"portfolio": {"initial_capital": 200_000},
                                   "intraday": {"strategy_limits": {"max_daily_loss_pct": 0.02,
                                                                    "max_consecutive_losses": 0}}})
    assert (g.strategy_max_daily_loss_pct, g.strategy_max_consecutive_losses, g.capital) == (0.02, 0, 200_000)
