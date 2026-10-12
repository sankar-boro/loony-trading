"""GET /api/intraday/desk and POST /api/intraday/control
(dashboard/backend/routers/intraday_desk.py)."""
from __future__ import annotations
import json
import time
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import utils.timeutils as timeutils
from dashboard.backend.routers import intraday_desk
from utils.bot_control import read_control

NOW = datetime(2026, 10, 12, 11, 0, tzinfo=timeutils.IST)


@pytest.fixture()
def files(tmp_path, monkeypatch):
    paths = {"state": tmp_path / "state.json", "trades": tmp_path / "trades.jsonl",
             "pnl": tmp_path / "pnl.jsonl", "control": tmp_path / "ctl.json"}
    monkeypatch.setattr(intraday_desk, "_STATE_FILE", paths["state"])
    monkeypatch.setattr(intraday_desk, "_LIVE_LOG", paths["trades"])
    monkeypatch.setattr(intraday_desk, "_PNL_FILE", paths["pnl"])
    monkeypatch.setattr(intraday_desk, "_CONTROL_FILE", paths["control"])
    monkeypatch.setattr(timeutils, "now_ist", lambda: NOW)
    monkeypatch.setattr(timeutils, "_is_holiday", lambda d: False)
    return paths


@pytest.fixture()
def client(files):
    app = FastAPI()
    app.include_router(intraday_desk.router, prefix="/api")
    return TestClient(app)


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_no_bot_falls_back_to_config(client):
    d = client.get("/api/intraday/desk").json()
    assert d["bot"]["running"] is False and d["positions"] == []
    assert d["session"]["phase"] == "entry_window"
    assert d["session"]["mins_to_squareoff"] == 254
    assert d["guard"]["entry_start"] == "09:30" and d["guard"]["trades_today"] == 0
    assert d["pnl"]["day"] == 0


def test_aggregates_bot_state_trades_and_curve(client, files):
    files["state"].write_text(json.dumps({
        "source": "main", "mode": "paper", "saved_at": time.time(), "initial_capital": 500_000,
        "last_tick_at": time.time() - 3, "exchange_stops": False,
        "positions": [{"symbol": "TCS", "direction": 1, "size": 10, "entry_price": 100,
                       "current_price": 98, "unrealised_pnl": -20.0, "stop_order_id": ""}],
        "intraday": {"session_date": "2026-10-12", "entry_start": "09:30", "entry_end": "14:45",
                     "trades_today": 3, "max_trades_per_day": 20, "max_daily_loss_pct": 0.01,
                     "halted": False, "paused": False},
        "events": [{"ts": "2026-10-12T10:59:00+05:30", "kind": "entry", "message": "a"},
                   {"ts": "2026-10-12T10:59:30+05:30", "kind": "exit", "message": "b"},
                   {"ts": "2026-10-09T10:00:00+05:30", "kind": "exit", "message": "old"}],
    }))
    _jsonl(files["trades"], [
        {"ts": "2026-10-12T04:00:00+00:00", "type": "close", "symbol": "INFY", "pnl": 300.0, "strategy": "orb"},
        {"ts": "2026-10-12T05:00:00+00:00", "type": "close", "symbol": "SBIN", "pnl": -100.0, "strategy": "orb"},
        {"ts": "2026-10-12T05:10:00+00:00", "type": "close", "symbol": "ITC", "pnl": 50.0, "strategy": "vwap"},
        {"ts": "2026-10-12T05:00:00+00:00", "type": "order", "symbol": "SBIN"},
        {"ts": "2026-10-09T05:00:00+00:00", "type": "close", "symbol": "OLD", "pnl": 999.0, "strategy": "orb"},
    ])
    _jsonl(files["pnl"], [{"ts": "2026-10-09T15:00:00+05:30", "total": 1},
                          {"ts": "2026-10-12T10:00:00+05:30", "total": 5},
                          {"ts": "2026-10-12T10:01:00+05:30", "total": 7}])

    d = client.get("/api/intraday/desk").json()

    assert d["bot"]["running"] and d["bot"]["mode"] == "paper" and not d["bot"]["feed_stale"]
    assert [t["symbol"] for t in d["trades"]] == ["INFY", "SBIN", "ITC"]
    assert d["pnl"] == {"realised": 250.0, "unrealised": -20.0, "day": 230.0, "capital": 500_000,
                        "loss_limit": 5000.0, "loss_used_pct": 0.0, "profit_lock": 0.0}
    assert d["by_strategy"][0] == {"strategy": "orb", "trades": 2, "wins": 1, "pnl": 200.0}
    assert [p["total"] for p in d["curve"]] == [5, 7]
    assert [e["message"] for e in d["events"]] == ["b", "a"]      # newest first, today only
    assert d["guard"]["trades_today"] == 3


def test_stale_state_from_yesterday_is_not_shown_as_today(client, files):
    files["state"].write_text(json.dumps({
        "source": "main", "mode": "live", "saved_at": time.time() - 86_400,
        "intraday": {"session_date": "2026-10-09", "trades_today": 9, "halted": True},
    }))
    d = client.get("/api/intraday/desk").json()
    assert d["bot"]["running"] is False
    assert d["guard"]["trades_today"] == 0 and d["guard"]["halted"] is False


def test_feed_stale_when_no_ticks_in_market_hours(client, files):
    files["state"].write_text(json.dumps({"source": "main", "mode": "live", "saved_at": time.time(),
                                          "last_tick_at": time.time() - 600}))
    assert client.get("/api/intraday/desk").json()["bot"]["feed_stale"] is True


@pytest.mark.parametrize("hhmm,phase", [("09:00", "pre_open"), ("09:20", "opening"),
                                        ("12:00", "entry_window"), ("15:00", "manage_only"),
                                        ("15:20", "squareoff"), ("16:00", "closed")])
def test_session_phases(hhmm, phase):
    h, m = map(int, hhmm.split(":"))
    now = NOW.replace(hour=h, minute=m)
    assert intraday_desk._session(now, "09:30", "14:45")["phase"] == phase


def test_weekend():
    sat = NOW.replace(day=10)
    s = intraday_desk._session(sat, "09:30", "14:45")
    assert s["phase"] == "weekend" and s["mins_to_squareoff"] == 0


def test_control_actions(client, files):
    r = client.post("/api/intraday/control", json={"action": "pause"})
    assert r.status_code == 200 and r.json()["control"]["paused"] is True
    client.post("/api/intraday/control", json={"action": "flatten"})
    assert read_control(files["control"])["flatten_id"]
    assert client.get("/api/intraday/desk").json()["control"]["paused"] is True
    assert client.post("/api/intraday/control", json={"action": "nuke"}).status_code == 400
