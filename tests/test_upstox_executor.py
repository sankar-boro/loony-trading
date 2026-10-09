"""
Tests for UpstoxExecutor — paper mode fills, risk sizing,
GTT orders, position management. No real API calls.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from execution_engine.upstox_executor import (
    UpstoxExecutor, UpstoxOrder, UpstoxProduct, UpstoxOrderType
)
from data_engine.upstox.auth import UpstoxAuth
from data_engine.upstox.instruments import InstrumentRegistry, KNOWN_INSTRUMENTS
from risk_manager.risk_manager import RiskManager, Position
from strategies.base import Signal, SignalType


# ── Fixtures ───────────────────────────────────────────────────────────────────

def make_auth():
    auth = MagicMock(spec=UpstoxAuth)
    auth.access_token = "test_token"
    auth.auth_header = {"Authorization": "Bearer test_token", "Accept": "application/json"}
    return auth


def make_registry():
    reg = MagicMock(spec=InstrumentRegistry)
    reg.get_key.side_effect = lambda sym: KNOWN_INSTRUMENTS.get(sym.upper())
    reg.get_lot_size.return_value = 1
    reg.get_tick_size.return_value = 0.05
    reg.round_to_tick.side_effect = lambda p, k: round(p, 2)
    return reg


CFG = {
    "risk": {
        "max_risk_per_trade": 0.01,
        "max_daily_drawdown": 0.05,
        "max_concurrent_trades": 10,
        "max_portfolio_risk": 0.20,
        "trailing_stop_pct": 0.02,
    },
    "execution": {
        "order_type": "limit",
        "slippage_pct": 0.0005,
        "retry_attempts": 2,
        "upstox_product": "CNC",
    },
}


@pytest.fixture
def executor():
    auth     = make_auth()
    registry = make_registry()
    rm       = RiskManager(CFG, initial_capital=500_000)
    return UpstoxExecutor(auth, registry, rm, CFG, mode="paper")


def make_signal(price=2900.0, sl=2840.0, tp=3020.0, conf=0.78):
    return Signal(
        strategy="test_strategy",
        symbol="RELIANCE",
        signal_type=SignalType.BUY,
        price=price,
        stop_loss=sl,
        take_profit=tp,
        confidence=conf,
    )


# ── Paper fill tests ───────────────────────────────────────────────────────────

def test_paper_fill_buy_adds_slippage(executor):
    order = UpstoxOrder(
        instrument_key="NSE_EQ|INE002A01018",
        quantity=5, product=UpstoxProduct.CNC,
        order_type=UpstoxOrderType.LIMIT,
        transaction_type="BUY",
        price=2900.0,
    )
    asyncio.run(
        executor._paper_fill(order, 2900.0)
    )
    assert order.status == "complete"
    assert order.avg_price > 2900.0  # slippage added on buy
    assert order.filled_qty == 5


def test_paper_fill_sell_subtracts_slippage(executor):
    order = UpstoxOrder(
        instrument_key="NSE_EQ|INE002A01018",
        quantity=5, product=UpstoxProduct.CNC,
        order_type=UpstoxOrderType.LIMIT,
        transaction_type="SELL",
        price=2900.0,
    )
    asyncio.run(
        executor._paper_fill(order, 2900.0)
    )
    assert order.avg_price < 2900.0  # slippage subtracted on sell


# ── Signal execution ───────────────────────────────────────────────────────────

def test_execute_signal_paper_returns_order(executor):
    sig = make_signal()
    order = asyncio.run(
        executor.execute_signal(sig)
    )
    assert order is not None
    assert order.status == "complete"
    assert order.transaction_type == "BUY"
    assert order.instrument_key == "NSE_EQ|INE002A01018"


def test_execute_signal_sell(executor):
    sig = Signal(
        strategy="test", symbol="RELIANCE",
        signal_type=SignalType.SELL, price=2900.0,
        stop_loss=2960.0, take_profit=2760.0, confidence=0.75,
    )
    order = asyncio.run(executor.execute_signal(sig))
    assert order is not None
    assert order.transaction_type == "SELL"


def test_execute_signal_low_confidence_rejected(executor):
    sig = make_signal(conf=0.30)  # below validation threshold of 0.5
    order = asyncio.run(executor.execute_signal(sig))
    assert order is None


def test_execute_unknown_symbol_returns_none(executor):
    sig = Signal(
        strategy="test", symbol="FAKESTK",
        signal_type=SignalType.BUY, price=100.0,
        stop_loss=95.0, take_profit=110.0, confidence=0.8,
    )
    order = asyncio.run(executor.execute_signal(sig))
    assert order is None


# ── Close position ─────────────────────────────────────────────────────────────

def test_close_position_paper(executor):
    sig = make_signal()
    asyncio.run(executor.execute_signal(sig))
    pos_list = executor.risk_manager.positions.get("RELIANCE", [])
    assert len(pos_list) > 0
    pos = pos_list[0]
    close_order = asyncio.run(
        executor.close_position(pos, 2950.0, "take_profit")
    )
    assert close_order is not None
    assert close_order.transaction_type == "SELL"
    assert executor.risk_manager.capital > 490_000  # should have gained some


# ── Order type selection ───────────────────────────────────────────────────────

def test_choose_order_type_limit(executor):
    sig = make_signal(conf=0.70)
    ot = UpstoxExecutor._choose_order_type(sig, "limit")
    assert ot == UpstoxOrderType.LIMIT


def test_choose_order_type_market(executor):
    sig = make_signal(conf=0.70)
    ot = UpstoxExecutor._choose_order_type(sig, "market")
    assert ot == UpstoxOrderType.MARKET


def test_choose_order_type_smart_high_conf(executor):
    sig = make_signal(conf=0.90)
    ot = UpstoxExecutor._choose_order_type(sig, "smart")
    assert ot == UpstoxOrderType.MARKET


def test_choose_order_type_smart_low_conf(executor):
    sig = make_signal(conf=0.70)
    ot = UpstoxExecutor._choose_order_type(sig, "smart")
    assert ot == UpstoxOrderType.LIMIT


# ── Resolve key ───────────────────────────────────────────────────────────────

def test_resolve_key_passthrough(executor):
    key = executor._resolve_key("NSE_EQ|INE002A01018")
    assert key == "NSE_EQ|INE002A01018"


def test_resolve_key_symbol(executor):
    key = executor._resolve_key("RELIANCE")
    assert key == "NSE_EQ|INE002A01018"


def test_resolve_key_unknown(executor):
    key = executor._resolve_key("GHOST999")
    assert key is None


# ── Order history ──────────────────────────────────────────────────────────────

def test_order_history_grows(executor):
    sig = make_signal()
    asyncio.run(executor.execute_signal(sig))
    assert len(executor.order_history) == 1


def test_default_product_read_from_exchange_config():
    execution = {k: v for k, v in CFG["execution"].items() if k != "upstox_product"}
    cfg = {**CFG, "execution": execution, "exchanges": {"upstox": {"default_product": "MIS"}}}
    ex = UpstoxExecutor(make_auth(), make_registry(), RiskManager(cfg, 500_000), cfg, mode="paper")
    assert ex._default_product.value == "MIS"
