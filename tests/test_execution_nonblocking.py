"""Tests for the non-blocking execution I/O fix (docs/appendix/intraday-audit.md
§4/§7 item 4): UpstoxExecutor's async methods must not block the shared
asyncio event loop with synchronous `requests` calls — main.py's live
tick stream runs on that same loop, so a blocked order-placement call
would delay stop-loss checks for every other open position."""
from __future__ import annotations
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from execution_engine.upstox_executor import (
    UpstoxExecutor, UpstoxOrder, UpstoxProduct, UpstoxOrderType,
)
from data_engine.upstox.auth import UpstoxAuth
from data_engine.upstox.instruments import InstrumentRegistry, KNOWN_INSTRUMENTS
from risk_manager.risk_manager import RiskManager


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
    "risk": {"max_risk_per_trade": 0.01, "max_daily_drawdown": 0.05,
              "max_concurrent_trades": 10, "max_portfolio_risk": 0.20,
              "trailing_stop_pct": 0.02},
    "execution": {"order_type": "limit", "slippage_pct": 0.0005,
                   "retry_attempts": 2, "upstox_product": "CNC"},
}


def make_executor(mode="live") -> UpstoxExecutor:
    rm = RiskManager(CFG, initial_capital=500_000)
    return UpstoxExecutor(make_auth(), make_registry(), rm, CFG, mode=mode)


# ── Wrapper correctness ──────────────────────────────────────────────────

def test_post_async_returns_same_result_as_sync_post():
    executor = make_executor()
    executor._post = MagicMock(return_value={"data": {"order_id": "abc123"}})

    result = asyncio.run(executor._post_async("/order/place", {"x": 1}))

    assert result == {"data": {"order_id": "abc123"}}
    executor._post.assert_called_once_with("/order/place", {"x": 1})


def test_get_async_returns_same_result_as_sync_get():
    executor = make_executor()
    executor._get = MagicMock(return_value={"data": {"status": "complete"}})

    result = asyncio.run(executor._get_async("/order/details", {"order_id": "abc123"}))

    assert result == {"data": {"status": "complete"}}
    executor._get.assert_called_once_with("/order/details", {"order_id": "abc123"})


def test_put_async_and_delete_async_delegate_correctly():
    executor = make_executor()
    executor._put = MagicMock(return_value={"data": {}})
    executor._delete = MagicMock(return_value={"data": {}})

    asyncio.run(executor._put_async("/order/modify", {"order_id": "x"}))
    asyncio.run(executor._delete_async("/order/cancel", {"order_id": "x"}))

    executor._put.assert_called_once_with("/order/modify", {"order_id": "x"})
    executor._delete.assert_called_once_with("/order/cancel", {"order_id": "x"})


# ── The actual property that matters: doesn't block the event loop ──────

def test_post_async_does_not_block_other_coroutines():
    """The core proof: while a slow 'HTTP call' is in flight via
    _post_async, another coroutine on the same event loop must keep
    making progress — this is exactly what was broken before (a
    synchronous requests.Session().post() call froze the whole loop,
    including main.py's tick handler, for every other symbol).

    Counting how many heartbeats eventually happen isn't enough to prove
    this — asyncio.gather() waits for every coroutine to finish either
    way, so a fully-blocking implementation still lets all 10 heartbeats
    complete, just bunched together *after* the blocking call returns.
    What actually distinguishes blocking from non-blocking is *when*
    those heartbeats land relative to the 0.3s call — interleaved
    throughout it (non-blocking) vs. all delayed until after it
    (blocking)."""
    executor = make_executor()

    def slow_post(endpoint, payload):
        time.sleep(0.3)   # simulates a slow synchronous HTTP round-trip
        return {"data": {"order_id": "abc123"}}

    executor._post = slow_post

    heartbeat_times: list[float] = []

    async def run_both():
        start = time.monotonic()

        async def heartbeat():
            for _ in range(10):
                heartbeat_times.append(time.monotonic() - start)
                await asyncio.sleep(0.02)

        await asyncio.gather(
            executor._post_async("/order/place", {}),
            heartbeat(),
        )

    asyncio.run(run_both())

    # A blocking implementation delays every single heartbeat until at
    # least the 0.3s mark (proven above: 0 land before 0.25s). A
    # non-blocking one lets most/all of them land well within that
    # window instead.
    early_ticks = [t for t in heartbeat_times if t < 0.25]
    assert len(early_ticks) >= 5, f"heartbeats were not interleaved — event loop was blocked: {heartbeat_times}"


# ── Wiring: the real async methods actually use the wrappers ────────────

@pytest.mark.asyncio
async def test_live_place_uses_post_async_not_blocking_post():
    executor = make_executor(mode="live")
    executor._post_async = AsyncMock(return_value={"data": {"order_id": "ord1", "status": "complete"}})
    executor._get_async = AsyncMock(return_value={"data": {"status": "complete", "average_price": 100.0,
                                                             "filled_quantity": 1, "exchange_order_id": "exch1"}})
    executor._post = MagicMock(side_effect=AssertionError("blocking _post must not be called directly"))
    executor._get = MagicMock(side_effect=AssertionError("blocking _get must not be called directly"))

    order = UpstoxOrder(
        instrument_key="NSE_EQ|INE002A01018", quantity=1, product=UpstoxProduct.CNC,
        order_type=UpstoxOrderType.LIMIT, transaction_type="BUY", price=100.0,
    )
    await executor._live_place(order)

    executor._post_async.assert_called_once()
    executor._get_async.assert_called_once()
    assert order.status == "complete"


@pytest.mark.asyncio
async def test_modify_and_cancel_order_use_async_wrappers():
    executor = make_executor(mode="live")
    executor._put_async = AsyncMock(return_value={"data": {}})
    executor._delete_async = AsyncMock(return_value={"data": {}})
    executor._put = MagicMock(side_effect=AssertionError("blocking _put must not be called directly"))
    executor._delete = MagicMock(side_effect=AssertionError("blocking _delete must not be called directly"))

    assert await executor.modify_order("ord1", price=105.0) is True
    assert await executor.cancel_order("ord1") is True
    executor._put_async.assert_called_once()
    executor._delete_async.assert_called_once()
