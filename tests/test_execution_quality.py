"""Execution improvements: limit-order chasing, the execution log and its
report, never booking an unfilled close, and v3 GTT stops for delivery."""
from __future__ import annotations
import asyncio
import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import execution_engine.upstox_executor as ex_mod
from analytics.execution_quality import report
from execution_engine.upstox_executor import UpstoxExecutor, UpstoxOrderType
from risk_manager.risk_manager import RiskManager
from tests.test_upstox_executor import CFG, make_auth, make_registry, make_signal


def _executor(mode="paper", product="CNC", **execution):
    cfg = {**CFG, "execution": {**CFG["execution"], "upstox_product": product, **execution}}
    return UpstoxExecutor(make_auth(), make_registry(), RiskManager(cfg, 500_000), cfg, mode=mode)


def _log():
    path = ex_mod._EXECUTION_LOG
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


# ── Execution log ────────────────────────────────────────────────────────────

def test_paper_entry_is_logged_with_slippage():
    ex = _executor()
    order = asyncio.run(ex.execute_signal(make_signal(price=1000.0, sl=980.0, tp=1040.0)))
    assert order.status == "complete"
    [rec] = _log()
    assert rec["kind"] == "entry" and rec["mode"] == "paper" and rec["outcome"] == "filled"
    assert rec["decision_price"] == 1000.0 and rec["slippage_bps"] == pytest.approx(5.0)   # 0.05 % paper slippage
    assert rec["strategy"] == "test_strategy" and rec["chases"] == 0


# ── Limit chasing (live) ─────────────────────────────────────────────────────

def _live_with_unfilled_limit(fill_on_chase: int | None, ltp=1003.0, **execution):
    ex = _executor(mode="live", chase_attempts=3, chase_wait_sec=0, max_chase_pct=0.003, **execution)
    polls = {"n": 0}

    async def place(order):
        order.order_id, order.status = "OID1", "open"

    async def poll(order, timeout_sec=30):
        polls["n"] += 1
        if fill_on_chase is not None and polls["n"] >= fill_on_chase:
            order.status, order.avg_price, order.filled_qty = "complete", order.price, order.quantity

    ex._live_place = place
    ex._poll_order_status = poll
    ex._ltp = MagicMock(side_effect=lambda key: asyncio.sleep(0, result=ltp))
    ex.modify_order = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0, result=True))
    ex.cancel_order = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0, result=True))
    return ex


def test_unfilled_limit_is_chased_toward_the_market_and_fills():
    ex = _live_with_unfilled_limit(fill_on_chase=1)
    order = asyncio.run(ex.execute_signal(make_signal(price=1000.0, sl=980.0, tp=1040.0)))
    assert order.status == "complete" and order.price == 1003.0           # moved to the LTP, within 0.3 %
    assert ex.modify_order.call_count == 1 and not ex.cancel_order.called
    assert _log()[-1]["chases"] == 1 and _log()[-1]["outcome"] == "filled"


def test_chase_never_goes_past_the_cap_and_unfilled_is_cancelled():
    ex = _live_with_unfilled_limit(fill_on_chase=None, ltp=1050.0)       # market ran away
    order = asyncio.run(ex.execute_signal(make_signal(price=1000.0, sl=980.0, tp=1040.0)))
    prices = [c.kwargs["price"] for c in ex.modify_order.call_args_list]
    assert prices == [1003.0]                                              # capped, then nothing left to chase
    assert order.status == "cancelled" and ex.cancel_order.called
    assert ex.risk_manager.open_count == 0
    assert _log()[-1]["outcome"] == "unfilled"


def test_market_orders_are_not_chased():
    ex = _live_with_unfilled_limit(fill_on_chase=None, order_type="market")
    asyncio.run(ex.execute_signal(make_signal(price=1000.0, sl=980.0, tp=1040.0)))
    assert not ex.modify_order.called


# ── Closing ──────────────────────────────────────────────────────────────────

def test_failed_live_close_is_never_booked_and_is_retried_later(monkeypatch):
    ex = _executor(mode="live")
    pos = ex.risk_manager.open_position(make_signal(price=1000.0, sl=980.0, tp=1040.0), 10)
    calls = {"n": 0}

    async def rejected(order):
        calls["n"] += 1
        order.status = "rejected"

    ex._live_place = rejected
    assert asyncio.run(ex.close_position(pos, 990.0, "stop_loss")) is None
    assert ex.risk_manager.open_count == 1                                 # still tracked
    assert asyncio.run(ex.close_position(pos, 990.0, "stop_loss")) is None
    assert calls["n"] == 1                                                 # backoff: no second order yet
    assert _log()[-1]["kind"] == "exit" and _log()[-1]["outcome"] == "rejected"

    async def filled(order):
        order.status, order.avg_price, order.filled_qty = "complete", 989.5, order.quantity
    ex._live_place = filled
    monkeypatch.setattr(ex_mod, "_CLOSE_RETRY_SEC", 0)
    order = asyncio.run(ex.close_position(pos, 990.0, "stop_loss"))
    assert order and ex.risk_manager.open_count == 0


# ── GTT (v3) ─────────────────────────────────────────────────────────────────

def test_place_gtt_uses_the_v3_payload():
    ex = _executor(mode="live")
    ex._post = MagicMock(return_value={"status": "success", "data": {"gtt_order_ids": ["GTT-C1"]}})
    gtt = ex.place_gtt("RELIANCE", "SELL", 10, ex._default_product, 980.0, "BELOW")
    url, payload = ex._post.call_args.args
    assert url == "https://api.upstox.com/v3/order/gtt/place"
    assert payload["product"] == "D" and payload["type"] == "SINGLE" and payload["quantity"] == 10
    assert payload["rules"] == [{"strategy": "ENTRY", "trigger_type": "BELOW", "trigger_price": 980.0}]
    assert gtt.gtt_id == "GTT-C1"


def test_cancel_gtt_sends_a_json_body():
    ex = _executor(mode="live")
    ex._delete = MagicMock(return_value={"status": "success"})
    assert ex.cancel_gtt("GTT-C1")
    assert ex._delete.call_args.kwargs["body"] == {"gtt_order_id": "GTT-C1"}
    assert ex._delete.call_args.args[0].endswith("/v3/order/gtt/cancel")


def _cnc_position(ex):
    pos = ex.risk_manager.open_position(make_signal(price=1000.0, sl=980.0, tp=1040.0), 10)
    return pos


def test_cnc_exchange_stop_is_a_gtt_and_trails():
    ex = _executor(mode="live", product="CNC")
    ex._post = MagicMock(return_value={"data": {"gtt_order_ids": ["GTT-C9"]}})
    ex._put = MagicMock(return_value={"status": "success"})
    pos = _cnc_position(ex)
    assert asyncio.run(ex.place_exchange_stop(pos)) == "GTT-C9" and pos.stop_synced == 980.0
    pos.stop_loss = 990.0
    assert asyncio.run(ex.sync_exchange_stop(pos))
    body = ex._put.call_args.args[1]
    assert body["gtt_order_id"] == "GTT-C9" and body["rules"][0]["trigger_price"] == 990.0


def test_mis_exchange_stop_stays_an_sl_m_order():
    ex = _executor(mode="live", product="MIS")
    ex._post_async = MagicMock(side_effect=lambda *a: asyncio.sleep(0, result={"data": {"order_id": "O7"}}))
    pos = _cnc_position(ex)
    assert asyncio.run(ex.place_exchange_stop(pos)) == "O7"
    assert ex._post_async.call_args.args[1]["order_type"] == "SL-M"


def test_gtt_stop_status_triggered_vanished_and_cancelled():
    ex = _executor(mode="live", product="CNC")
    pos = _cnc_position(ex)
    pos.stop_order_id, pos.stop_synced = "GTT-C9", 980.0
    ex.get_gtt = MagicMock(return_value={"rules": [{"status": "TRIGGERED", "order_id": "OX"}]})
    ex._get_async = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0, result={
        "data": {"status": "complete", "average_price": 979.5, "filled_quantity": 10}}))
    assert asyncio.run(ex.exchange_stop_status(pos)) == {"status": "complete", "avg_price": 979.5, "filled_qty": 10}

    key = ex._resolve_key("RELIANCE")
    ex.get_gtt = MagicMock(return_value=None)                              # no longer listed
    ex.fetch_broker_quantities = MagicMock(side_effect=lambda: asyncio.sleep(0, result=({key: 0}, {})))
    assert asyncio.run(ex.exchange_stop_status(pos))["status"] == "complete"
    ex.fetch_broker_quantities = MagicMock(side_effect=lambda: asyncio.sleep(0, result=({key: 10}, {})))
    assert asyncio.run(ex.exchange_stop_status(pos))["status"] == "cancelled"
    assert asyncio.run(ex.cancel_exchange_stop(pos)) and pos.stop_order_id == ""


def test_restore_keeps_gtt_stops_across_days(tmp_path, monkeypatch):
    import utils.timeutils as tu
    from tests.test_bot_state_persistence import _FakeBot, _buy, _on_day
    _on_day(monkeypatch, 9)
    bot = _FakeBot(tmp_path / "state.json", product="CNC")
    a = bot.risk_manager.open_position(_buy("RELIANCE"), 10)
    b = bot.risk_manager.open_position(_buy("TCS"), 10)
    a.stop_order_id, b.stop_order_id = "GTT-C1", "240101000123"
    bot._save_state(force=True)
    _on_day(monkeypatch, 12)
    fresh = _FakeBot(tmp_path / "state.json", product="CNC")
    fresh._restore_state()
    ids = {p.symbol: p.stop_order_id for lst in fresh.risk_manager.positions.values() for p in lst}
    assert ids == {"RELIANCE": "GTT-C1", "TCS": ""}


# ── Report ───────────────────────────────────────────────────────────────────

def _rows():
    base = {"mode": "paper", "strategy": "orb", "qty": 10, "latency_ms": 100}
    return [
        {**base, "ts": "2026-10-19T09:40:00+05:30", "kind": "entry", "order_type": "LIMIT", "chases": 1,
         "fill_price": 101.0, "filled_qty": 10, "slippage_bps": 10.0, "outcome": "filled"},
        {**base, "ts": "2026-10-19T10:10:00+05:30", "kind": "entry", "order_type": "LIMIT", "chases": 0,
         "fill_price": None, "filled_qty": 0, "slippage_bps": None, "outcome": "unfilled"},
        {**base, "ts": "2026-10-19T14:20:00+05:30", "kind": "exit", "order_type": "MARKET", "chases": 0,
         "fill_price": 99.0, "filled_qty": 10, "slippage_bps": -2.0, "outcome": "filled"},
        {**base, "ts": "2026-10-19T11:00:00+05:30", "mode": "live", "kind": "entry", "order_type": "LIMIT",
         "chases": 0, "fill_price": 50.0, "filled_qty": 2, "slippage_bps": 4.0, "outcome": "filled"},
    ]


def test_report_aggregates():
    now = datetime.fromisoformat("2026-10-19T16:00:00+05:30")
    r = report(_rows(), days=7, mode="paper", now=now)
    assert r["overall"]["orders"] == 3 and r["overall"]["fill_rate_pct"] == pytest.approx(66.7)
    assert r["overall"]["avg_slippage_bps"] == pytest.approx(4.0)
    assert r["overall"]["slippage_cost"] == pytest.approx(1.01 - 0.198, abs=0.01)
    assert r["outcomes"] == {"filled": 2, "unfilled": 1}
    assert {g["key"] for g in r["by_kind"]} == {"entry", "exit"}
    assert {g["key"] for g in r["by_chases"]} == {"0", "1"}
    assert [g["key"] for g in r["by_hour"]] == ["09", "10", "14"]
    assert report(_rows(), days=7, now=now)["overall"]["orders"] == 4


def test_execution_quality_endpoint(tmp_path, monkeypatch):
    import analytics.execution_quality as eq
    from dashboard.backend.routers.trades import router
    path = tmp_path / "ex.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in _rows()))
    monkeypatch.setattr(eq, "EXECUTION_LOG", path)
    monkeypatch.setattr(eq, "report", lambda rows, days, mode: {"n": len(rows), "mode": mode})
    app = FastAPI()
    app.include_router(router, prefix="/api")
    assert TestClient(app).get("/api/execution/quality?mode=live").json() == {"n": 4, "mode": "live"}
