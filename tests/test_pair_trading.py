"""Pair trading: numpy cointegration statistics, the stateless strategy,
the pair backtester, and the live bot opening/closing both legs together."""
from __future__ import annotations
import asyncio
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backtester.pair_backtester import run_pair_backtest
from strategies.base import SignalType
from strategies.stat_arb.pair_trading import PairTradingStrategy
from utils.kalman import coint_critical_value, engle_granger_stat, half_life

N = 400


def _series(seed=7, phi=0.85, beta=1.2, n=N):
    rng = np.random.default_rng(seed)
    b = np.cumsum(rng.normal(0, 1, n)) + 200
    sp = np.zeros(n)
    for t in range(1, n):
        sp[t] = phi * sp[t - 1] + rng.normal(0, 1.5)
    return beta * b + sp + 20, b


def _frame(x, start="2025-01-01"):
    return pd.DataFrame({"close": np.asarray(x, float)},
                        index=pd.date_range(start, periods=len(x), freq="B"))


def _stretched(z_sign=+1, k=5.0):
    """A cointegrated pair whose last bar puts the spread k std devs out."""
    a, b = _series()
    sd = np.std(a - np.polyval(np.polyfit(b, a, 1), b))
    a = a.copy()
    a[-1] += z_sign * k * sd
    return a, b


# ── Statistics ───────────────────────────────────────────────────────────────

def test_engle_granger_separates_cointegrated_from_random_walks():
    a, b = _series()
    c = np.cumsum(np.random.default_rng(3).normal(0, 1, N)) + 200
    assert engle_granger_stat(a, b) < coint_critical_value(0.05) < engle_granger_stat(c, b)
    assert coint_critical_value(0.01) < coint_critical_value(0.10)


def test_half_life():
    _, _ = _series()
    rng = np.random.default_rng(0)
    s = np.zeros(2000)
    for t in range(1, 2000):
        s[t] = 0.9 * s[t - 1] + rng.normal()
    assert half_life(s) == pytest.approx(-np.log(2) / (0.9 - 1), rel=0.25)
    assert half_life(np.cumsum(np.ones(50))) == float("inf")


# ── Strategy ─────────────────────────────────────────────────────────────────

def test_evaluate_marks_cointegrated_pair_tradable_and_rejects_random_walks():
    s = PairTradingStrategy({})
    a, b = _series()
    st = s.evaluate(s.align(_frame(a), _frame(b)))
    assert st.tradable and st.beta == pytest.approx(1.2, abs=0.1)
    c = np.cumsum(np.random.default_rng(3).normal(0, 1, N)) + 200
    bad = s.evaluate(s.align(_frame(c), _frame(b)))
    assert not bad.tradable and "not cointegrated" in bad.reason
    assert s.evaluate(s.align(_frame(a[:50]), _frame(b[:50]))) is None     # too little history


def test_entry_sides_and_determinism():
    s = PairTradingStrategy({})
    a, b = _stretched(+1)
    da, db = _frame(a), _frame(b)
    st = s.evaluate(s.align(da, db))
    assert st.z > s.entry_z
    assert st.entry_sides(s.entry_z) == (SignalType.SELL, SignalType.BUY)   # A rich: short A
    first = s.generate_pair_signals(da, db, "A", "B")
    again = s.generate_pair_signals(da, db, "A", "B")
    assert first[0].signal_type == SignalType.SELL and first[1].signal_type == SignalType.BUY
    assert (first[0].confidence, first[0].metadata["spread_z"]) == \
           (again[0].confidence, again[0].metadata["spread_z"])            # stateless


def test_exit_reason():
    s = PairTradingStrategy({"strategies": {"params": {"pair_trading": {"max_hold_bars": 10}}}})
    st = SimpleNamespace(z=-0.3)
    assert "reverted" in s.exit_reason(st, +1)
    assert s.exit_reason(SimpleNamespace(z=-1.5), +1) is None
    assert "stop" in s.exit_reason(SimpleNamespace(z=-4.5), +1)
    assert "reverted" in s.exit_reason(SimpleNamespace(z=0.2), -1)
    assert "time stop" in s.exit_reason(SimpleNamespace(z=-1.5), +1, bars_held=10)


def test_leg_quantities_are_beta_hedged():
    s = PairTradingStrategy({})
    qa, qb = s.leg_quantities(SimpleNamespace(beta=1.5), price_a=250.0, capital=500_000)
    assert qa == 200 and qb == 300                              # 10 % of capital in A


# ── Backtester ───────────────────────────────────────────────────────────────

def test_pair_backtest_profits_on_a_cointegrated_pair_and_skips_random_walks():
    cfg = {"execution": {"slippage_pct": 0.0005, "commission_futures": 0.0006}}
    a, b = _series(n=600)
    r = run_pair_backtest(_frame(a), _frame(b), "A", "B", cfg)
    assert r.metrics["n_trades"] >= 3 and r.metrics["total_return_pct"] > 0
    t = r.pair_trades[0]
    assert t.qty_b == pytest.approx(t.qty_a * 1.2, rel=0.15)
    c = np.cumsum(np.random.default_rng(3).normal(0, 1, 600)) + 200
    assert run_pair_backtest(_frame(c), _frame(b), "C", "B", cfg).metrics["n_trades"] == 0


def test_pair_backtest_pays_costs():
    a, b = _series(n=600)
    free = run_pair_backtest(_frame(a), _frame(b), "A", "B",
                             {"execution": {"slippage_pct": 0, "commission_futures": 0}})
    costly = run_pair_backtest(_frame(a), _frame(b), "A", "B",
                               {"execution": {"slippage_pct": 0.001, "commission_futures": 0.002}})
    assert costly.equity_curve[-1] < free.equity_curve[-1]


# ── Live bot ─────────────────────────────────────────────────────────────────

def _pair_bot(monkeypatch, product="MIS", fail_leg=None):
    from tests.test_bot_position_safety import _FakeBot, _at
    bot = _FakeBot(product=product)
    _at(monkeypatch, 11, 0)
    bot._pairs = [("HDFCBANK", "ICICIBANK")]
    bot._pair_strategy = PairTradingStrategy({})
    a, b = _stretched(+1)
    bot._df_cache["HDFCBANK"], bot._df_cache["ICICIBANK"] = _frame(a), _frame(b)
    bot._last_price.update(HDFCBANK=float(a[-1]), ICICIBANK=float(b[-1]))
    bot.risk_manager.cfg["max_sector_exposure"] = 0                  # both legs are Banking

    async def execute(signal, quantity=None, product=None):
        bot.executor.executed.append((signal.symbol, signal.signal_type, quantity))
        if signal.symbol == fail_leg:
            return None
        bot.risk_manager.open_position(signal, quantity)
        return SimpleNamespace(status="complete", filled_qty=quantity, quantity=quantity,
                               avg_price=signal.price)
    bot.executor.execute_signal = execute
    return bot


def test_bot_opens_both_legs_as_one_pair(monkeypatch):
    bot = _pair_bot(monkeypatch)
    asyncio.run(bot._check_pairs("HDFCBANK", pd.Timestamp("2026-10-12 11:00", tz="Asia/Kolkata")))
    sides = [(s, t) for s, t, _ in bot.executor.executed]
    assert sides == [("HDFCBANK", SignalType.SELL), ("ICICIBANK", SignalType.BUY)]
    a = bot.risk_manager.positions["HDFCBANK"][0]
    b = bot.risk_manager.positions["ICICIBANK"][0]
    assert a.pair_id and a.pair_id == b.pair_id and a.direction == -1 and b.direction == 1
    assert "Pair HDFCBANK/ICICIBANK" in bot._events[-1]["message"]
    assert bot.guard.trades_today == 2


def test_cnc_bot_never_opens_a_pair(monkeypatch):
    bot = _pair_bot(monkeypatch, product="CNC")
    asyncio.run(bot._check_pairs("HDFCBANK", pd.Timestamp("2026-10-12 11:00", tz="Asia/Kolkata")))
    assert bot.executor.executed == []
    assert "cannot hold one" in bot._events[-1]["message"]


def test_failed_second_leg_unwinds_the_first(monkeypatch):
    bot = _pair_bot(monkeypatch, fail_leg="ICICIBANK")
    asyncio.run(bot._check_pairs("HDFCBANK", pd.Timestamp("2026-10-12 11:00", tz="Asia/Kolkata")))
    assert bot.risk_manager.open_count == 0
    assert ("HDFCBANK", "pair_unwind") in bot.executor.closed


def _open_pair(monkeypatch):
    bot = _pair_bot(monkeypatch)
    asyncio.run(bot._check_pairs("HDFCBANK", pd.Timestamp("2026-10-12 11:00", tz="Asia/Kolkata")))
    assert bot.risk_manager.open_count == 2
    return bot


def test_reverted_spread_closes_both_legs(monkeypatch):
    bot = _open_pair(monkeypatch)
    a, b = _series()                                     # last bar back near the mean
    bot._df_cache["HDFCBANK"], bot._df_cache["ICICIBANK"] = _frame(a), _frame(b)
    asyncio.run(bot._check_pairs("ICICIBANK", pd.Timestamp("2026-10-12 12:00", tz="Asia/Kolkata")))
    assert bot.risk_manager.open_count == 0
    assert all(r.startswith("pair_exit") for _, r in bot.executor.closed)


def test_one_leg_stopped_out_closes_the_other(monkeypatch):
    bot = _open_pair(monkeypatch)
    leg = bot.risk_manager.positions["HDFCBANK"][0]
    asyncio.run(bot._close_tracked(leg, leg.stop_loss, "stop_loss"))
    assert bot.risk_manager.open_count == 0
    assert ("ICICIBANK", "pair_leg_closed (HDFCBANK)") in bot.executor.closed


def test_other_strategies_do_not_close_a_pair_leg(monkeypatch):
    from tests.test_bot_position_safety import _signal
    bot = _open_pair(monkeypatch)
    ok = asyncio.run(bot._handle_existing_position(_signal("HDFCBANK", SignalType.BUY), 100.0))
    assert ok is False and bot.risk_manager.open_count == 2


def test_squareoff_does_not_double_close_pair_legs(monkeypatch):
    bot = _open_pair(monkeypatch)
    asyncio.run(bot._squareoff_mis())                    # paper, MIS
    assert bot.risk_manager.open_count == 0
    assert sorted(r for _, r in bot.executor.closed) == ["mis_squareoff", "mis_squareoff"]
