import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from strategies.base import Signal, SignalType
from risk_manager.risk_manager import RiskManager


def make_signal(price: float = 100.0, sl: float = 95.0, tp: float = 110.0,
                confidence: float = 0.75) -> Signal:
    return Signal(
        strategy="test", symbol="BTC/USDT",
        signal_type=SignalType.BUY, price=price,
        stop_loss=sl, take_profit=tp, confidence=confidence,
    )


CFG = {
    "risk": {
        "max_risk_per_trade": 0.01,
        "max_daily_drawdown": 0.05,
        "max_concurrent_trades": 5,
        "max_portfolio_risk": 0.20,
        "trailing_stop_pct": 0.02,
    }
}


def test_validate_signal_passes():
    rm = RiskManager(CFG, 10_000)
    sig = make_signal()
    assert rm.validate_signal(sig) is True


def test_validate_signal_low_confidence():
    rm = RiskManager(CFG, 10_000)
    sig = make_signal(confidence=0.3)
    assert rm.validate_signal(sig) is False


def test_position_size_positive():
    rm = RiskManager(CFG, 10_000)
    sig = make_signal()
    size = rm.size_position(sig)
    assert size > 0


def test_position_size_respects_risk_pct():
    rm = RiskManager(CFG, 10_000)
    sig = make_signal(price=100, sl=99, tp=110)  # 1% SL distance
    size = rm.size_position(sig)
    risk_used = size * abs(sig.price - sig.stop_loss)
    max_risk = 10_000 * 0.01
    assert risk_used <= max_risk * 1.001


def test_max_concurrent_trades():
    rm = RiskManager(CFG, 10_000)
    for i in range(5):
        sig = make_signal()
        sig.symbol = f"SYM{i}/USDT"
        rm.open_position(sig, 0.1)
    sig = make_signal()
    sig.symbol = "NEW/USDT"
    assert rm.validate_signal(sig) is False


def test_trailing_stop_updates():
    rm = RiskManager(CFG, 10_000)
    sig = make_signal(price=100, sl=95, tp=115)
    pos = rm.open_position(sig, 1.0)
    pos.update_trailing_stop(105)
    assert pos.stop_loss > 95


def test_daily_drawdown_blocks():
    rm = RiskManager(CFG, 10_000)
    rm.daily_pnl = -600  # 6% of 10k, above 5% limit
    sig = make_signal()
    assert rm.validate_signal(sig) is False
