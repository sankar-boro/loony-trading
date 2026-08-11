"""Tests for the Phase 5 watchlists & alerts feature: condition DSL
validation/matching, the evaluate_alerts() engine, and the watchlist/alert
CRUD routers."""
from __future__ import annotations
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base, get_db
from db import models as m
from signals.alerts import validate_condition, _condition_matches, evaluate_alerts
from dashboard.backend.routers.watchlists import router as watchlists_router
from dashboard.backend.routers.alerts import router as alerts_router


# ── validate_condition ───────────────────────────────────────────────────

def test_validate_condition_rejects_empty():
    assert validate_condition({}) is not None


def test_validate_condition_rejects_missing_operator_suffix():
    err = validate_condition({"score": 80})
    assert err is not None
    assert "score" in err


def test_validate_condition_rejects_unknown_field():
    err = validate_condition({"relative_volume__gt": 2})
    assert err is not None
    assert "unknown field" in err


def test_validate_condition_rejects_unknown_operator():
    err = validate_condition({"score__between": 80})
    assert err is not None


def test_validate_condition_accepts_valid_condition():
    assert validate_condition({"score__gt": 80, "confidence__gte": 70}) is None


# ── _condition_matches ───────────────────────────────────────────────────

def _signal(**overrides) -> m.Signal:
    defaults = dict(
        stock_id=1, direction=m.SignalDirection.BULLISH, score=85.0, confidence=75.0,
        catalyst_score=90.0, technical_score=60.0, momentum_score=50.0, volume_score=95.0,
        historical_score=50.0, regime_score=50.0, risk_score=20.0,
    )
    defaults.update(overrides)
    return m.Signal(**defaults)


def test_condition_matches_single_field():
    matched = _condition_matches(_signal(), {"score__gt": 80})
    assert matched == {"score": 85.0}


def test_condition_matches_and_composition_all_must_pass():
    matched = _condition_matches(_signal(), {"score__gt": 80, "volume_score__gte": 95})
    assert matched == {"score": 85.0, "volume_score": 95.0}


def test_condition_matches_and_composition_fails_if_any_fails():
    matched = _condition_matches(_signal(), {"score__gt": 80, "volume_score__gte": 99})
    assert matched is None


def test_condition_matches_direction_field_compares_enum_value():
    matched = _condition_matches(_signal(), {"direction__eq": "bullish"})
    assert matched == {"direction": "bullish"}


def test_condition_matches_direction_field_mismatch():
    assert _condition_matches(_signal(), {"direction__eq": "bearish"}) is None


# ── DB fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def client():
    from fastapi import FastAPI

    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(watchlists_router, prefix="/api")
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


# ── evaluate_alerts end-to-end ───────────────────────────────────────────

def test_evaluate_alerts_fires_for_matching_stock(db_session):
    stock = m.Stock(symbol="RELIANCE", company_name="Reliance Industries")
    db_session.add(stock)
    db_session.flush()
    db_session.add(_signal(stock_id=stock.id, score=85.0))
    alert = m.Alert(name="High score", condition={"score__gt": 80}, is_active=True)
    db_session.add(alert)
    db_session.commit()

    summary = evaluate_alerts(db_session)

    assert summary.alerts_checked == 1
    assert len(summary.triggers) == 1
    assert summary.triggers[0].symbol == "RELIANCE"
    assert summary.triggers[0].matched_values == {"score": 85.0}

    db_session.refresh(alert)
    assert alert.triggered_at is not None
    triggers = db_session.query(m.AlertTrigger).all()
    assert len(triggers) == 1
    assert triggers[0].matched_values == {"score": 85.0}


def test_evaluate_alerts_skips_non_matching_stock(db_session):
    stock = m.Stock(symbol="TCS", company_name="TCS")
    db_session.add(stock)
    db_session.flush()
    db_session.add(_signal(stock_id=stock.id, score=40.0))
    alert = m.Alert(name="High score", condition={"score__gt": 80}, is_active=True)
    db_session.add(alert)
    db_session.commit()

    summary = evaluate_alerts(db_session)

    assert summary.alerts_checked == 1
    assert summary.triggers == []
    assert db_session.query(m.AlertTrigger).count() == 0


def test_evaluate_alerts_ignores_inactive_alerts(db_session):
    stock = m.Stock(symbol="INFY", company_name="Infosys")
    db_session.add(stock)
    db_session.flush()
    db_session.add(_signal(stock_id=stock.id, score=95.0))
    db_session.add(m.Alert(name="Disabled", condition={"score__gt": 80}, is_active=False))
    db_session.commit()

    summary = evaluate_alerts(db_session)

    assert summary.alerts_checked == 0
    assert summary.triggers == []


def test_evaluate_alerts_scoped_to_single_stock_ignores_others(db_session):
    reliance = m.Stock(symbol="RELIANCE", company_name="Reliance Industries")
    tcs = m.Stock(symbol="TCS", company_name="TCS")
    db_session.add_all([reliance, tcs])
    db_session.flush()
    db_session.add(_signal(stock_id=reliance.id, score=90.0))
    db_session.add(_signal(stock_id=tcs.id, score=90.0))
    alert = m.Alert(name="Reliance only", stock_id=reliance.id, condition={"score__gt": 80}, is_active=True)
    db_session.add(alert)
    db_session.commit()

    summary = evaluate_alerts(db_session)

    assert len(summary.triggers) == 1
    assert summary.triggers[0].symbol == "RELIANCE"


def test_evaluate_alerts_uses_latest_signal_per_stock(db_session):
    """A stale signal that once matched must not re-fire once superseded
    by a newer non-matching signal for the same stock."""
    stock = m.Stock(symbol="HDFC", company_name="HDFC Bank")
    db_session.add(stock)
    db_session.flush()
    db_session.add(_signal(stock_id=stock.id, score=95.0, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    db_session.add(_signal(stock_id=stock.id, score=10.0, timestamp=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    db_session.add(m.Alert(name="High score", condition={"score__gt": 80}, is_active=True))
    db_session.commit()

    summary = evaluate_alerts(db_session)

    assert summary.triggers == []


# ── Watchlist CRUD ────────────────────────────────────────────────────────

def test_create_and_list_watchlist(client):
    resp = client.post("/api/watchlists", json={"name": "Swing Trades"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Swing Trades"
    assert body["symbols"] == []

    resp = client.get("/api/watchlists")
    assert len(resp.json()) == 1


def test_add_and_remove_watchlist_item(client):
    db = _db(client)
    db.add(m.Stock(symbol="RELIANCE", company_name="Reliance Industries"))
    db.commit()

    created = client.post("/api/watchlists", json={"name": "Core"}).json()
    resp = client.post(f"/api/watchlists/{created['id']}/items", json={"symbol": "reliance"})
    assert resp.status_code == 200
    assert resp.json()["symbols"] == ["RELIANCE"]

    resp = client.delete(f"/api/watchlists/{created['id']}/items/RELIANCE")
    assert resp.json()["symbols"] == []


def test_add_watchlist_item_unknown_symbol_404s(client):
    created = client.post("/api/watchlists", json={"name": "Core"}).json()
    resp = client.post(f"/api/watchlists/{created['id']}/items", json={"symbol": "NOTREAL"})
    assert resp.status_code == 404


def test_delete_watchlist(client):
    created = client.post("/api/watchlists", json={"name": "Temp"}).json()
    resp = client.delete(f"/api/watchlists/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/watchlists").json() == []


# ── Alert CRUD + evaluate endpoint ────────────────────────────────────────

def test_create_alert_rejects_invalid_condition(client):
    resp = client.post("/api/alerts", json={"name": "Bad", "condition": {"foo__gt": 1}})
    assert resp.status_code == 400


def test_create_alert_rejects_unknown_symbol(client):
    resp = client.post("/api/alerts", json={
        "name": "Bad", "condition": {"score__gt": 80}, "symbol": "NOTREAL",
    })
    assert resp.status_code == 404


def test_create_toggle_delete_alert(client):
    created = client.post("/api/alerts", json={"name": "My Alert", "condition": {"score__gt": 80}}).json()
    assert created["is_active"] is True

    resp = client.patch(f"/api/alerts/{created['id']}?is_active=false")
    assert resp.json()["is_active"] is False

    resp = client.delete(f"/api/alerts/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/alerts").json() == []


def test_evaluate_endpoint_fires_and_triggers_are_listable(client):
    db = _db(client)
    stock = m.Stock(symbol="RELIANCE", company_name="Reliance Industries")
    db.add(stock)
    db.flush()
    db.add(_signal(stock_id=stock.id, score=90.0))
    db.commit()

    created = client.post("/api/alerts", json={"name": "High score", "condition": {"score__gt": 80}}).json()

    resp = client.post("/api/alerts/evaluate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["alerts_checked"] == 1
    assert len(body["triggers"]) == 1
    assert body["triggers"][0]["symbol"] == "RELIANCE"

    triggers = client.get(f"/api/alerts/{created['id']}/triggers").json()
    assert len(triggers) == 1
    assert triggers[0]["symbol"] == "RELIANCE"
