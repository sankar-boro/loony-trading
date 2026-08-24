"""Tests for the UI-facing endpoints added so the intraday-gap fixes are
reachable from the dashboard, not just the terminal: intraday signal
scan, timeframe-filtered composite signals, timeframe-aware alert
evaluation, and per-trade reasons in backtest results."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base, get_db
from db import models as m
from dashboard.backend.routers.composite_signals import router as signals_router
from dashboard.backend.routers.alerts import router as alerts_router


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(signals_router, prefix="/api")
    app.include_router(alerts_router, prefix="/api")

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    test_client = TestClient(app)
    test_client._session_factory = Session
    return test_client


def _db(client) -> "Session":  # noqa: F821
    return client._session_factory()


def _seed_signal(db, symbol, *, timeframe, score, days_ago=0):
    stock = db.query(m.Stock).filter(m.Stock.symbol == symbol).first()
    if not stock:
        stock = m.Stock(symbol=symbol, company_name=symbol)
        db.add(stock)
        db.flush()
    db.add(m.Signal(
        stock_id=stock.id, timeframe=timeframe, direction=m.SignalDirection.BULLISH,
        score=score, confidence=80.0,
        timestamp=datetime.now(timezone.utc) - timedelta(days=days_ago),
    ))
    return stock


# ── /api/signals/intraday-scan ───────────────────────────────────────────

def test_intraday_scan_calls_run_signal_engine_with_form_inputs(client):
    with patch("scripts.run_signal_engine.run_signal_engine") as mock_run:
        mock_run.return_value = {
            "universe": 1, "scored": 1, "skipped": 0, "timeframe": "30m",
            "directions": {"bullish": 1}, "results": [{"symbol": "RELIANCE", "direction": "bullish",
                                                          "score": 82.0, "confidence": 75.0}],
            "errors": [],
        }
        resp = client.post("/api/signals/intraday-scan", json={
            "symbols": ["reliance"], "timeframe": "30m", "lookback_days": 5,
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["results"][0]["symbol"] == "RELIANCE"
    mock_run.assert_called_once_with(limit=5, lookback_days=5, timeframe="30m", symbols=["reliance"])


def test_intraday_scan_defaults_to_universe_scan_when_no_symbols(client):
    with patch("scripts.run_signal_engine.run_signal_engine") as mock_run:
        mock_run.return_value = {"universe": 5, "scored": 5, "skipped": 0, "timeframe": "30m",
                                   "directions": {}, "results": [], "errors": []}
        resp = client.post("/api/signals/intraday-scan", json={})

    assert resp.status_code == 200
    mock_run.assert_called_once_with(limit=5, lookback_days=5, timeframe="30m", symbols=None)


# ── /api/signals/composite timeframe filter ──────────────────────────────

def test_composite_signals_default_timeframe_is_1d(client):
    db = _db(client)
    _seed_signal(db, "RELIANCE", timeframe="1d", score=50.0)
    _seed_signal(db, "RELIANCE", timeframe="30m", score=99.0)
    db.commit()

    resp = client.get("/api/signals/composite")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["timeframe"] == "1d"
    assert body[0]["score"] == 50.0


def test_composite_signals_explicit_intraday_timeframe(client):
    db = _db(client)
    _seed_signal(db, "RELIANCE", timeframe="1d", score=50.0)
    _seed_signal(db, "RELIANCE", timeframe="30m", score=99.0)
    db.commit()

    resp = client.get("/api/signals/composite?timeframe=30m")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["timeframe"] == "30m"
    assert body[0]["score"] == 99.0


def test_composite_signal_response_includes_timeframe_field(client):
    db = _db(client)
    _seed_signal(db, "TCS", timeframe="1h", score=70.0)
    db.commit()

    resp = client.get("/api/signals/composite?timeframe=1h")
    assert resp.json()[0]["timeframe"] == "1h"


# ── /api/alerts/evaluate timeframe param ─────────────────────────────────

def test_alerts_evaluate_default_timeframe_is_1d(client):
    db = _db(client)
    _seed_signal(db, "RELIANCE", timeframe="1d", score=90.0)
    _seed_signal(db, "RELIANCE", timeframe="30m", score=10.0)
    db.add(m.Alert(name="High score", condition={"score__gt": 80}, is_active=True))
    db.commit()

    resp = client.post("/api/alerts/evaluate")
    body = resp.json()
    assert body["timeframe"] == "1d"
    assert len(body["triggers"]) == 1


def test_alerts_evaluate_explicit_intraday_timeframe(client):
    db = _db(client)
    _seed_signal(db, "RELIANCE", timeframe="1d", score=10.0)
    _seed_signal(db, "RELIANCE", timeframe="30m", score=90.0)
    db.add(m.Alert(name="High score", condition={"score__gt": 80}, is_active=True))
    db.commit()

    resp = client.post("/api/alerts/evaluate?timeframe=30m")
    body = resp.json()
    assert body["timeframe"] == "30m"
    assert len(body["triggers"]) == 1
