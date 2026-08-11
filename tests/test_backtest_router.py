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

from dashboard.backend.routers.backtest import _monte_carlo_metrics


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
