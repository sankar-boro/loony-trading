"""Portfolio analytics (beta, hedge, factors, stress) for current holdings,
and the stress-scenario calibration."""
from __future__ import annotations
import json

import numpy as np
import pandas as pd
import pytest

from analytics.factor_model import FactorModel
from analytics.portfolio_analytics import FACTOR_INDICES, analyse, holdings
from backtester.stress_test import STRESS_SCENARIOS, calibrated_returns, run_stress_test

N = 260


def _market(seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=N, freq="B")
    m = rng.normal(0.0004, 0.01, N)
    frames = {}
    for name, sym in FACTOR_INDICES.items():
        r = m if name == "market" else m + rng.normal(0, 0.004, N)
        frames[sym] = pd.DataFrame({"close": 20000 * np.exp(np.cumsum(r))}, index=idx)
    return idx, m, frames


def _stock(idx, m, beta, seed):
    rng = np.random.default_rng(seed)
    r = beta * m + rng.normal(0, 0.008, N)
    return pd.DataFrame({"close": 1000 * np.exp(np.cumsum(r))}, index=idx)


def _fetch(frames):
    return lambda symbols, days: {s: frames[s] for s in symbols if s in frames}


def test_holdings_sign_shorts():
    book = holdings([{"symbol": "TCS", "size": 10, "current_price": 100, "direction": 1},
                     {"symbol": "INFY", "size": 5, "current_price": 200, "direction": -1}])
    assert book == {"TCS": 1000.0, "INFY": -1000.0}


def test_analyse_beta_factors_stress_and_json():
    idx, m, frames = _market()
    frames["TCS"] = _stock(idx, m, 1.5, 1)
    frames["ITC"] = _stock(idx, m, 0.5, 2)
    pos = [{"symbol": "TCS", "size": 100, "current_price": 1000, "direction": 1},
           {"symbol": "ITC", "size": 100, "current_price": 1000, "direction": 1}]
    a = analyse(pos, 500_000, _fetch(frames))
    json.dumps(a)                                                      # JSON-safe
    assert a["gross"] == 200_000 and a["missing"] == []
    assert a["beta"]["per_symbol"]["TCS"]["beta"] == pytest.approx(1.5, abs=0.25)
    assert a["beta"]["portfolio"] == pytest.approx(1.0, abs=0.2)
    assert a["beta"]["hedge"] is None and "below one Nifty futures lot" in a["beta"]["hedge_note"]
    assert a["factors"]["n_obs"] > 200 and a["factors"]["r_squared"] > 0.5
    assert a["stress"]["capital_beta"] == pytest.approx(a["beta"]["portfolio"] * 200_000 / 500_000, abs=1e-3)
    assert {s["key"] for s in a["stress"]["scenarios"]} == set(STRESS_SCENARIOS)


def test_big_book_gets_a_futures_hedge():
    idx, m, frames = _market()
    frames["TCS"] = _stock(idx, m, 1.2, 3)
    pos = [{"symbol": "TCS", "size": 4000, "current_price": 1000, "direction": 1}]
    a = analyse(pos, 5_000_000, _fetch(frames))
    h = a["beta"]["hedge"]
    assert h and h["direction"] == "sell" and h["lots"] >= 1


def test_no_positions():
    assert analyse([], 500_000, _fetch({})) == {"positions": 0}


def test_scenarios_compound_to_their_stated_total():
    for sc in STRESS_SCENARIOS.values():
        assert np.prod(1 + calibrated_returns(sc)) - 1 == pytest.approx(sc["nifty_total_pct"] / 100)


def test_stress_loss_scales_with_beta():
    full = run_stress_test([], 100_000, beta_vs_nifty=0.99, scenarios=["covid_2020"])
    half = run_stress_test([], 100_000, beta_vs_nifty=0.5, scenarios=["covid_2020"])
    assert full.results["covid_2020"].strategy_total_pct < half.results["covid_2020"].strategy_total_pct


def test_factor_sector_exposure_uses_the_universe():
    exp = FactorModel().sector_exposure({"HDFCBANK": 100, "TCS": 100, "MARUTI": 100, "RELIANCE": 100})
    assert exp == {"banking": 0.25, "it": 0.25, "auto": 0.25, "other": 0.25}
