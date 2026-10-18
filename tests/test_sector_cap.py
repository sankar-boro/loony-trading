"""Sector exposure cap (risk.max_sector_exposure) in RiskManager."""
from __future__ import annotations
import math

from risk_manager.risk_manager import RiskManager
from strategies.base import Signal, SignalType


def _sig(symbol: str, price: float = 1000.0) -> Signal:
    return Signal(symbol=symbol, signal_type=SignalType.BUY, confidence=0.9, price=price,
                  stop_loss=price * 0.98, take_profit=price * 1.04, strategy="t")


def test_sector_lookup_and_index_has_no_cap():
    rm = RiskManager({"risk": {}}, 500_000)
    assert rm.sector_of("HDFCBANK") == "Banking"
    assert rm.sector_of("NIFTY50") is None
    assert rm.sector_room("NIFTY50") == math.inf


def test_size_is_trimmed_to_sector_room_and_full_sector_rejected():
    rm = RiskManager({"risk": {"max_sector_exposure": 0.30, "max_portfolio_risk": 0.25}}, 500_000)
    rm.open_position(_sig("HDFCBANK"), 100)                # ₹1,00,000 in Banking
    assert rm.sector_room("ICICIBANK") == 50_000            # cap ₹1,50,000
    assert rm.size_position(_sig("ICICIBANK")) == 50        # trimmed from 125
    assert rm.size_position(_sig("TCS")) == 125             # IT untouched
    rm.open_position(_sig("SBIN"), 50)
    assert rm.sector_room("AXISBANK") == 0
    assert rm.validate_signal(_sig("AXISBANK")) is False
    assert rm.validate_signal(_sig("TCS")) is True


def test_cap_off_with_zero():
    rm = RiskManager({"risk": {"max_sector_exposure": 0}}, 500_000)
    rm.open_position(_sig("HDFCBANK"), 400)
    assert rm.sector_room("ICICIBANK") == math.inf
