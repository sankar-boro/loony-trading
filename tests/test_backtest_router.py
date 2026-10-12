"""Regression tests for dashboard/backend/routers/backtest.py helpers.

Locks in two bugs found via live verification while wiring Monte Carlo
into the Strategy Lab UI:
  1. `_monte_carlo_metrics` read `mc.return_mean`, which doesn't exist on
     `MCResult` (it's `final_return_mean`) — always raised AttributeError,
     silently swallowed into an {"error": ...} dict the UI never checked.
  2. Even after fixing the attribute name, `max_dd_mean`/`final_return_mean`
     are fractions (0.03 = 3%) but were passed straight into fields named
     `_pct` without scaling by 100, and the pnl values fed in were raw
     rupee amounts rather than the fractional per-trade returns
     `run_monte_carlo` expects — both produced nonsense (billions of
     percent) output.
"""
from __future__ import annotations

import numpy as np

from backtester.backtester import BacktestResult, Trade
from dashboard.backend.routers.backtest import _monte_carlo_metrics, _serialize_result


def test_monte_carlo_metrics_no_attribute_error():
    result = _monte_carlo_metrics([0.02, -0.01, 0.015, -0.005, 0.03, -0.02, 0.01])
    assert "error" not in result


def test_monte_carlo_metrics_are_percent_scaled_not_raw_fractions():
    # Small, realistic fractional per-trade returns (matching the docstring
    # contract: 0.02 = 2%) should produce single/low-double-digit percent
    # outputs, not values in the billions from feeding in raw rupee P&L.
    trade_returns = [0.02, -0.01, 0.015, -0.005, 0.03, -0.02, 0.01, 0.005, -0.015, 0.025]
    result = _monte_carlo_metrics(trade_returns)
    assert "error" not in result
    assert abs(result["return_mean_pct"]) < 100
    assert 0 <= result["max_dd_mean"] < 100
    assert 0 <= result["max_dd_p95"] < 100


# ── trade reasons in the serialized response (docs/appendix/intraday-audit.md §3, UI wiring) ──

def test_serialize_result_includes_per_trade_reason():
    trades = [
        Trade(symbol="RELIANCE", direction=1, entry_price=100.0, exit_price=105.0,
              size=10.0, entry_bar=5, exit_bar=20, pnl=50.0, strategy="s1", reason="take_profit"),
        Trade(symbol="RELIANCE", direction=1, entry_price=110.0, exit_price=108.0,
              size=10.0, entry_bar=25, exit_bar=40, pnl=-20.0, strategy="s1", reason="mis_squareoff"),
    ]
    result = BacktestResult(
        trades=trades, equity_curve=np.array([10_000.0, 10_050.0, 10_030.0]),
        metrics={"n_trades": 2, "win_rate": 50.0, "profit_factor": 2.5, "sharpe": 1.0,
                 "sortino": 1.0, "max_drawdown_pct": -0.2, "total_return_pct": 0.3,
                 "cagr_pct": 1.0, "avg_win": 50.0, "avg_loss": -20.0, "expectancy": 15.0,
                 "median_trade_return_pct": 1.0, "avg_holding_bars": 15.0},
        symbol="RELIANCE",
    )

    summary = _serialize_result(result)

    assert "trades" in summary
    assert len(summary["trades"]) == 2
    assert summary["trades"][0]["reason"] == "take_profit"
    assert summary["trades"][1]["reason"] == "mis_squareoff"
    assert summary["trades"][1]["pnl"] == -20.0
    # trades_pnl (used by the existing P&L histogram) stays unchanged
    assert summary["trades_pnl"] == [50.0, -20.0]


# ── every enabled strategy can be backtested on its own (Strategy Lab) ──────

def test_single_strategy_without_class_mapping_runs_through_engine(monkeypatch):
    import pandas as pd
    from dashboard.backend.routers import backtest as bt_router

    rng = np.random.default_rng(7)
    close = 1000 * np.exp(np.cumsum(rng.normal(0, 0.01, 700)))
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": rng.integers(1e5, 9e5, 700).astype(float)},
                      index=pd.date_range("2023-01-02", periods=700, freq="B"))
    monkeypatch.setattr(bt_router, "_fetch_ohlcv", lambda *a, **k: df)
    monkeypatch.setattr(bt_router, "get_backtest_jobs", lambda: jobs)
    jobs = {"j1": {"status": "pending"}}

    req = bt_router.BacktestRequest(symbol="RELIANCE", strategy="cumulative_delta", token="t")
    bt_router._run_backtest_sync("j1", req)

    assert jobs["j1"]["status"] == "done", jobs["j1"].get("error")
    assert "Unknown single strategy" not in str(jobs["j1"]["result"].get("errors", ""))
