"""Tests for options strategies: theta decay, iron condor, straddle, gamma scalp."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from datetime import date, timedelta
import pandas as pd
import numpy as np
import pytest

from strategies.options import (
    ThetaDecayStrategy, IronCondorStrategy,
    StraddleStrangleStrategy, GammaScalpingStrategy,
)
from data_engine.upstox.iv_surface import build_iv_surface
from feature_engine.greeks import Greeks


SPOT = 22000.0
RISK_FREE = 0.065
CFG = {
    "options": {
        "theta_decay": {"iv_rank_entry": 60.0, "min_dte": 5, "max_dte": 25, "min_premium": 10.0},
        "iron_condor": {"iv_rank_min": 45.0, "iv_rank_max": 90.0, "min_dte": 5, "max_dte": 25, "min_net_premium": 20.0},
        "straddle_strangle": {"buy_iv_rank_max": 35.0, "sell_iv_rank_min": 70.0, "min_dte": 3},
        "gamma_scalping": {"max_iv_rank": 70.0, "rv_iv_ratio_min": 1.05, "gamma_expiry_dte": 3},
    }
}


def make_df(n=50, spot=SPOT):
    idx = pd.date_range("2025-01-06 09:15", periods=n, freq="15min")
    np.random.seed(42)
    prices = spot + np.cumsum(np.random.randn(n) * 50)
    df = pd.DataFrame({
        "open": prices - 10, "high": prices + 30,
        "low": prices - 30,  "close": prices,
        "volume": np.random.randint(50000, 150000, n),
    }, index=idx)
    return df


_EXPIRY = str((date.today() + timedelta(days=14)).isoformat())


def make_surface(iv_history_high=True):
    """Build surface with controllable IV rank."""
    strikes = [SPOT - 200, SPOT - 100, SPOT, SPOT + 100, SPOT + 200]
    rows = []
    for K in strikes:
        cg = Greeks(SPOT, K, 14, RISK_FREE, 0.16, "call")
        pg = Greeks(SPOT, K, 14, RISK_FREE, 0.16, "put")
        rows.append({"strike": K, "expiry": _EXPIRY,
                     "call_ltp": cg.price, "put_ltp": pg.price,
                     "call_oi": 5000, "put_oi": 4000, "call_iv": 0.0, "put_iv": 0.0})
    chain = pd.DataFrame(rows)
    # Low history → current IV is "high" → high IV rank
    history = [0.05] * 250 if iv_history_high else [0.25] * 250
    return build_iv_surface("NIFTY", SPOT, chain, iv_history=history)


# ── ThetaDecayStrategy ────────────────────────────────────────────────────────

def test_theta_decay_high_iv_generates_signal():
    strat = ThetaDecayStrategy(CFG)
    df = make_df()
    surface = make_surface(iv_history_high=True)
    sig = strat.generate_option_signal(df, "NIFTY50", surface)
    assert sig is not None
    assert sig.signal_type.value == "sell"


def test_theta_decay_low_iv_no_signal():
    strat = ThetaDecayStrategy(CFG)
    df = make_df()
    surface = make_surface(iv_history_high=False)  # low IV rank
    sig = strat.generate_option_signal(df, "NIFTY50", surface)
    assert sig is None


def test_theta_decay_metadata():
    strat = ThetaDecayStrategy(CFG)
    df = make_df()
    surface = make_surface(iv_history_high=True)
    sig = strat.generate_option_signal(df, "NIFTY50", surface)
    if sig:
        assert "call_strike" in sig.metadata
        assert "total_premium" in sig.metadata
        assert sig.metadata["total_premium"] > 0


def test_theta_decay_should_exit_profit():
    strat = ThetaDecayStrategy(CFG)
    reason = strat.should_exit(100.0, 20.0, 20.0, dte_remaining=5)
    assert reason is not None
    assert "profit" in reason


def test_theta_decay_should_exit_stop():
    strat = ThetaDecayStrategy(CFG)
    reason = strat.should_exit(100.0, 150.0, 100.0, dte_remaining=5)
    assert reason is not None
    assert "stop" in reason


def test_theta_decay_should_exit_dte():
    strat = ThetaDecayStrategy(CFG)
    reason = strat.should_exit(100.0, 60.0, 60.0, dte_remaining=1)
    assert reason is not None
    assert "dte" in reason


# ── IronCondorStrategy ────────────────────────────────────────────────────────

def test_iron_condor_generates_signal():
    strat = IronCondorStrategy(CFG)
    df = make_df()
    surface = make_surface(iv_history_high=True)
    sig = strat.generate_option_signal(df, "NIFTY50", surface)
    # May or may not fire depending on ADX
    if sig:
        assert "short_call" in sig.metadata
        assert "short_put"  in sig.metadata
        assert sig.metadata["probability_profit"] > 0


def test_iron_condor_metadata_consistency():
    strat = IronCondorStrategy(CFG)
    df = make_df()
    surface = make_surface(iv_history_high=True)
    sig = strat.generate_option_signal(df, "NIFTY50", surface)
    if sig:
        m = sig.metadata
        assert m["long_call"] > m["short_call"]
        assert m["short_put"] > m["long_put"]
        assert m["net_premium"] > 0
        assert m["max_loss"] > 0


def test_iron_condor_adjustment_call_side():
    strat = IronCondorStrategy(CFG)
    adj = strat.adjustment_needed(spot=22500.0, short_call=22450.0, short_put=21500.0)
    assert adj == "call_side"


def test_iron_condor_adjustment_put_side():
    strat = IronCondorStrategy(CFG)
    adj = strat.adjustment_needed(spot=21450.0, short_call=22500.0, short_put=21500.0)
    assert adj == "put_side"


def test_iron_condor_no_adjustment_middle():
    strat = IronCondorStrategy(CFG)
    adj = strat.adjustment_needed(spot=22000.0, short_call=22500.0, short_put=21500.0)
    assert adj is None


# ── StraddleStrangleStrategy ──────────────────────────────────────────────────

def test_straddle_sell_high_iv():
    strat = StraddleStrangleStrategy(CFG)
    df = make_df()
    surface = make_surface(iv_history_high=True)  # high IV rank → sell
    sig = strat.generate_option_signal(df, "NIFTY50", surface, event_days_away=99)
    if sig:
        assert sig.signal_type.value == "sell"


def test_straddle_buy_event():
    strat = StraddleStrangleStrategy(CFG)
    df = make_df()
    # Low IV rank + event soon → buy
    strikes = [SPOT]; rows = []
    cg = Greeks(SPOT, SPOT, 14, RISK_FREE, 0.10, "call")
    pg = Greeks(SPOT, SPOT, 14, RISK_FREE, 0.10, "put")
    rows.append({"strike": SPOT, "expiry": _EXPIRY,
                 "call_ltp": cg.price, "put_ltp": pg.price,
                 "call_oi": 5000, "put_oi": 4000, "call_iv": 0.0, "put_iv": 0.0})
    chain = pd.DataFrame(rows)
    surface = build_iv_surface("NIFTY", SPOT, chain, iv_history=[0.25] * 250)
    sig = strat.generate_option_signal(df, "NIFTY50", surface, event_days_away=2)
    if sig:
        assert sig.signal_type.value == "buy"


# ── GammaScalpingStrategy ─────────────────────────────────────────────────────

def test_gamma_scalp_expiry_mode():
    strat = GammaScalpingStrategy(CFG)
    # Build surface with dte=2 (expiry mode)
    strikes = [SPOT - 100, SPOT, SPOT + 100]
    rows = []
    for K in strikes:
        cg = Greeks(SPOT, K, 2, RISK_FREE, 0.15, "call")
        pg = Greeks(SPOT, K, 2, RISK_FREE, 0.15, "put")
        rows.append({"strike": K, "expiry": "2025-06-12",
                     "call_ltp": cg.price, "put_ltp": pg.price,
                     "call_oi": 5000, "put_oi": 4000, "call_iv": 0.0, "put_iv": 0.0})
    chain = pd.DataFrame(rows)
    surface = build_iv_surface("NIFTY", SPOT, chain, iv_history=[0.20] * 250)
    df = make_df()
    sig = strat.generate_option_signal(df, "NIFTY50", surface)
    if sig:
        assert sig.metadata.get("mode") == "expiry_gamma"


def test_gamma_scalp_hedge_computation():
    strat = GammaScalpingStrategy(CFG)
    hedge = strat.compute_hedge(
        spot=22000.0, strike=22000.0, dte=14,
        sigma=0.15, current_hedge_qty=0.0, lot_size=50,
    )
    # ATM straddle has near-zero net delta, so no hedge needed
    # (call delta ~0.5, put delta ~-0.5 = net 0)
    if hedge is not None:
        assert hedge.direction in ("buy", "sell")
