"""Tests for IV surface builder and max pain calculation."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
import pandas as pd
import pytest
from data_engine.upstox.iv_surface import (
    build_iv_surface, _calculate_max_pain, IVPoint, IVSurface,
)
from feature_engine.greeks import Greeks

SPOT = 22000.0
RISK_FREE = 0.065
_EXPIRY = str((date.today() + timedelta(days=14)).isoformat())
_EXPIRY_SHORT = str((date.today() + timedelta(days=7)).isoformat())


def make_chain(spot=SPOT, dte=14):
    """Build synthetic option chain around spot."""
    strikes = [spot - 300, spot - 200, spot - 100, spot, spot + 100, spot + 200, spot + 300]
    rows = []
    for K in strikes:
        cg = Greeks(spot, K, dte, RISK_FREE, 0.15, "call")
        pg = Greeks(spot, K, dte, RISK_FREE, 0.15, "put")
        rows.append({
            "strike": K,
            "expiry": _EXPIRY,
            "call_ltp": cg.price,
            "put_ltp": pg.price,
            "call_oi": 10000 if abs(K - spot) < 150 else 5000,
            "put_oi":  8000  if abs(K - spot) < 150 else 4000,
            "call_iv": 0.0,
            "put_iv":  0.0,
        })
    return pd.DataFrame(rows)


def test_build_surface_not_empty():
    chain = make_chain()
    surface = build_iv_surface("NIFTY", SPOT, chain)
    assert len(surface.smiles) > 0


def test_atm_iv_is_positive():
    chain = make_chain()
    surface = build_iv_surface("NIFTY", SPOT, chain)
    assert surface.atm_iv() > 0.0


def test_pcr_computable():
    chain = make_chain()
    surface = build_iv_surface("NIFTY", SPOT, chain)
    pcr = surface.pcr()
    assert 0.0 < pcr < 5.0


def test_max_pain_near_spot():
    chain = make_chain()
    surface = build_iv_surface("NIFTY", SPOT, chain)
    mp = surface.max_pain()
    assert mp is not None
    assert abs(mp - SPOT) / SPOT < 0.02   # max pain within 2% of spot


def test_term_structure_sorted():
    chain1 = make_chain(dte=7);  chain1["expiry"] = _EXPIRY_SHORT
    chain2 = make_chain(dte=14); chain2["expiry"] = _EXPIRY
    chain  = pd.concat([chain1, chain2], ignore_index=True)
    surface = build_iv_surface("NIFTY", SPOT, chain)
    ts = surface.term_structure()
    days = [d for d, _ in ts]
    assert days == sorted(days)


def test_iv_rank_with_history():
    chain = make_chain()
    history = [0.10, 0.12, 0.15, 0.18, 0.20] * 50   # 250 values
    surface = build_iv_surface("NIFTY", SPOT, chain, iv_history=history)
    rank = surface.iv_rank_current()
    assert 0.0 <= rank <= 100.0


def test_is_high_iv():
    chain = make_chain()
    history = [0.05] * 250   # historically low vol → current 15% is "high"
    surface = build_iv_surface("NIFTY", SPOT, chain, iv_history=history)
    assert surface.is_high_iv(rank_threshold=70.0)


def test_summary_dict():
    chain = make_chain()
    surface = build_iv_surface("NIFTY", SPOT, chain)
    s = surface.summary()
    assert "atm_iv" in s
    assert "iv_rank" in s
    assert "pcr" in s
    assert "max_pain" in s


def test_max_pain_calculation():
    points = [
        IVPoint(strike=22000, expiry="2025-06-12", days_to_expiry=14,
                call_iv=0.15, put_iv=0.15, mid_iv=0.15, call_price=50.0, put_price=50.0,
                call_delta=0.5, put_delta=-0.5, call_oi=5000, put_oi=3000),
        IVPoint(strike=22100, expiry="2025-06-12", days_to_expiry=14,
                call_iv=0.15, put_iv=0.15, mid_iv=0.15, call_price=30.0, put_price=70.0,
                call_delta=0.4, put_delta=-0.4, call_oi=8000, put_oi=2000),
        IVPoint(strike=21900, expiry="2025-06-12", days_to_expiry=14,
                call_iv=0.15, put_iv=0.15, mid_iv=0.15, call_price=70.0, put_price=30.0,
                call_delta=0.6, put_delta=-0.6, call_oi=2000, put_oi=9000),
    ]
    mp = _calculate_max_pain(points, 22000.0)
    assert mp in {22000, 22100, 21900}


def test_empty_chain_returns_surface():
    empty = pd.DataFrame()
    surface = build_iv_surface("NIFTY", SPOT, empty)
    assert isinstance(surface, IVSurface)
    assert surface.atm_iv() != surface.atm_iv()  # nan
