"""Tests for the Phase 4 '/stocks/{symbol}/why' explainability endpoint."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base, get_db
from db import models as m
from dashboard.backend.routers.composite_signals import router


@pytest.fixture()
def client():
    from fastapi import FastAPI

    # StaticPool pins all connections to the same in-memory DB — otherwise
    # each Session() gets its own empty :memory: database.
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(router, prefix="/api")

    def _override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    test_client = TestClient(app)
    test_client._session_factory = Session  # stash for direct DB seeding in tests
    return test_client


def _db(client) -> "Session":  # noqa: F821
    return client._session_factory()


def test_why_unknown_symbol_returns_404(client):
    resp = client.get("/api/stocks/NOTREAL/why")
    assert resp.status_code == 404


def test_why_no_data_reports_insufficient_evidence(client):
    db = _db(client)
    db.add(m.Stock(symbol="TEST", company_name="Test Co"))
    db.commit()

    resp = client.get("/api/stocks/TEST/why")
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal"] is None
    assert body["drivers"] == []
    assert "Insufficient evidence" in body["conclusion"]


def test_why_ranks_drivers_by_weighted_contribution(client):
    db = _db(client)
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db.add(stock)
    db.flush()
    db.add(m.Signal(
        stock_id=stock.id, direction=m.SignalDirection.BULLISH, score=75.0, confidence=80.0,
        catalyst_score=90.0, technical_score=60.0, momentum_score=50.0, volume_score=50.0,
        historical_score=50.0, regime_score=50.0, risk_score=50.0,
        explanation={
            "catalyst": 90.0, "technical": 60.0, "momentum": 50.0, "volume": 50.0,
            "historical": 50.0, "regime": 50.0, "risk": 50.0,
        },
    ))
    db.commit()

    resp = client.get("/api/stocks/TEST/why")
    body = resp.json()
    assert body["signal"]["direction"] == "bullish"
    # catalyst: 90*0.25=22.5 is the top contributor despite technical having a higher weight*raw product check
    assert body["drivers"][0]["factor"] == "catalyst"
    assert body["drivers"][0]["contribution"] == pytest.approx(22.5)
    assert "news catalyst" in body["conclusion"].lower()


def test_why_includes_recent_news_with_source_attribution(client):
    db = _db(client)
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db.add(stock)
    db.flush()
    article = m.NewsArticle(
        source="Reuters", title="Test Co beats estimates", url="https://example.com/a",
        published_at=datetime.now(timezone.utc), hash="why-test-1",
    )
    db.add(article)
    db.flush()
    event = m.NewsEvent(
        article_id=article.id, event_type="earnings", impact_score=0.7,
        catalyst_score=8.0, sentiment_score=0.6, confidence=0.8, summary="Beat estimates",
    )
    db.add(event)
    db.flush()
    db.add(m.StockEvent(stock_id=stock.id, event_id=event.id, relevance_score=1.0, direction="bullish"))
    db.commit()

    resp = client.get("/api/stocks/TEST/why")
    body = resp.json()
    assert len(body["recent_news"]) == 1
    assert body["recent_news"][0]["url"] == "https://example.com/a"
    assert body["recent_news"][0]["source"] == "Reuters"


def test_why_excludes_stale_news_outside_lookback(client):
    db = _db(client)
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db.add(stock)
    db.flush()
    article = m.NewsArticle(
        source="Reuters", title="Old news", url="https://example.com/old",
        published_at=datetime.now(timezone.utc) - timedelta(days=30), hash="why-test-old",
    )
    db.add(article)
    db.flush()
    event = m.NewsEvent(
        article_id=article.id, event_type="earnings", impact_score=0.7,
        catalyst_score=8.0, sentiment_score=0.6, confidence=0.8,
    )
    db.add(event)
    db.flush()
    old_se = m.StockEvent(stock_id=stock.id, event_id=event.id, relevance_score=1.0, direction="bullish")
    old_se.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db.add(old_se)
    db.commit()

    resp = client.get("/api/stocks/TEST/why")
    assert resp.json()["recent_news"] == []


def test_why_historical_analogue_reflects_real_seeded_data(client):
    db = _db(client)
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db.add(stock)
    db.flush()
    article = m.NewsArticle(
        source="Reuters", title="Test Co beats", url="https://example.com/b",
        published_at=datetime.now(timezone.utc), hash="why-test-2",
    )
    db.add(article)
    db.flush()
    event = m.NewsEvent(
        article_id=article.id, event_type="earnings", impact_score=0.7,
        catalyst_score=8.0, sentiment_score=0.6, confidence=0.8,
    )
    db.add(event)
    db.flush()
    db.add(m.StockEvent(stock_id=stock.id, event_id=event.id, relevance_score=1.0, direction="bullish"))
    # 5 matured analogues, 4 winners -> 80% win rate, hand-verifiable
    for i, r in enumerate([2.0, 1.0, -0.5, 3.0, 0.5]):
        db.add(m.HistoricalEvent(
            stock_id=stock.id, event_type="earnings", direction="bullish",
            event_timestamp=datetime.now(timezone.utc) - timedelta(days=i + 10),
            price_before=100.0, price_after_1d=100.0 * (1 + r / 100),
        ))
    db.commit()

    resp = client.get("/api/stocks/TEST/why")
    body = resp.json()
    assert body["historical_analogue"]["sample_count"] == 5
    assert body["historical_analogue"]["win_rate_pct"] == pytest.approx(80.0)
    assert "not a prediction" in body["historical_analogue"]["label"].lower()
