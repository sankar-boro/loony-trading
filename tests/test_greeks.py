"""Tests for Black-Scholes Greeks and IV solver."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import pytest
from feature_engine.greeks import (
    Greeks, implied_volatility, iv_rank, iv_percentile, delta_to_strike,
)


def test_call_price_basic():
    g = Greeks(S=100, K=100, T=30, r=0.065, sigma=0.20, opt="call")
    assert 1.0 < g.price < 15.0


def test_put_price_basic():
    g = Greeks(S=100, K=100, T=30, r=0.065, sigma=0.20, opt="put")
    assert 1.0 < g.price < 15.0


def test_put_call_parity():
    S, K, T, r, sigma = 100.0, 100.0, 30.0, 0.065, 0.20
    call = Greeks(S, K, T, r, sigma, "call")
    put  = Greeks(S, K, T, r, sigma, "put")
    # C - P = S - K*e^(-rT)
    lhs = call.price - put.price
    rhs = S - K * math.exp(-r * T / 365.0)
    assert abs(lhs - rhs) < 0.02


def test_call_delta_range():
    g = Greeks(S=100, K=100, T=30, r=0.065, sigma=0.20, opt="call")
    assert 0.0 < g.delta < 1.0


def test_put_delta_range():
    g = Greeks(S=100, K=100, T=30, r=0.065, sigma=0.20, opt="put")
    assert -1.0 < g.delta < 0.0


def test_gamma_positive():
    g = Greeks(S=100, K=100, T=30, r=0.065, sigma=0.20)
    assert g.gamma > 0.0


def test_theta_negative():
    g = Greeks(S=100, K=100, T=30, r=0.065, sigma=0.20)
    assert g.theta < 0.0   # time decay costs money


def test_vega_positive():
    g = Greeks(S=100, K=100, T=30, r=0.065, sigma=0.20)
    assert g.vega > 0.0


def test_deep_itm_call_delta_near_one():
    g = Greeks(S=150, K=100, T=30, r=0.065, sigma=0.20, opt="call")
    assert g.delta > 0.9


def test_deep_otm_call_delta_near_zero():
    g = Greeks(S=100, K=200, T=30, r=0.065, sigma=0.20, opt="call")
    assert g.delta < 0.05


def test_implied_volatility_roundtrip():
    S, K, T, r, sigma_true = 100.0, 100.0, 30.0, 0.065, 0.25
    call = Greeks(S, K, T, r, sigma_true, "call")
    iv = implied_volatility(call.price, S, K, T, r, "call")
    assert not math.isnan(iv)
    assert abs(iv - sigma_true) < 0.002


def test_iv_rank_midpoint():
    history = list(range(10, 50))   # IV range 10-49
    rank = iv_rank(30.0, history)
    assert 40 < rank < 60


def test_iv_percentile_basic():
    history = [10.0, 15.0, 20.0, 25.0, 30.0]
    pct = iv_percentile(22.0, history)
    assert pct == 60.0   # 3 out of 5 values below 22


def test_delta_to_strike_25d():
    S, T, r, sigma = 22000.0, 7.0, 0.065, 0.15
    K = delta_to_strike(S, T, r, sigma, 0.25, "call")
    g = Greeks(S, K, T, r, sigma, "call")
    assert abs(g.delta - 0.25) < 0.02


def test_zero_dte_handles_gracefully():
    g = Greeks(S=100, K=100, T=0, r=0.065, sigma=0.20, opt="call")
    assert g.price >= 0.0


def test_moneyness():
    itm  = Greeks(S=110, K=100, T=30, r=0.065, sigma=0.20, opt="call")
    atm  = Greeks(S=100, K=100, T=30, r=0.065, sigma=0.20, opt="call")
    otm  = Greeks(S=90,  K=100, T=30, r=0.065, sigma=0.20, opt="call")
    assert itm.moneyness() == "ITM"
    assert atm.moneyness() == "ATM"
    assert otm.moneyness() == "OTM"
