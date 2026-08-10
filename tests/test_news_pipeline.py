"""Tests for the Phase 1 news ingestion pipeline."""
from __future__ import annotations
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db import models as m
from ai.schemas import StructuredAnalysis
from data_engine.news.classifier import NewsClassifier, NEWS_EVENT_TYPES
from data_engine.news.demo_provider import DemoNewsProvider
from data_engine.news.entity_resolution import resolve_stock_mentions
from data_engine.news.pipeline import NewsIngestionPipeline
from data_engine.news.provider import RawNewsItem


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ── entity resolution ────────────────────────────────────────────────────────

def test_resolve_stock_mentions_finds_symbol_and_company_name():
    assert resolve_stock_mentions("Reliance Industries beats Q1 estimates") == ["RELIANCE"]
    assert resolve_stock_mentions("RELIANCE stock surges 3%") == ["RELIANCE"]


def test_resolve_stock_mentions_no_false_positive():
    assert resolve_stock_mentions("Completely unrelated text about the weather today") == []


def test_resolve_stock_mentions_multiple_stocks():
    result = resolve_stock_mentions("HDFC Bank and ICICI Bank both rallied on RBI's rate decision")
    assert "HDFCBANK" in result
    assert "ICICIBANK" in result


def test_resolve_stock_mentions_ticker_word_collision_regression():
    # PERSISTENT (Persistent Systems) is also an ordinary English word —
    # lowercase prose use must not match the ticker.
    assert "PERSISTENT" not in resolve_stock_mentions(
        "The RBI held rates steady, citing persistent food-price inflation."
    )
    # An actual uppercase ticker mention still resolves.
    assert "PERSISTENT" in resolve_stock_mentions(
        "PERSISTENT Systems reported strong Q2 revenue growth."
    )


# ── classifier normalization ─────────────────────────────────────────────────

class _StubProvider:
    def __init__(self, event_type: str):
        self._event_type = event_type

    def complete_structured(self, *, system, prompt, schema):
        return schema(
            summary="stub", event_type=self._event_type, direction="bullish",
            confidence=0.7, catalyst_score=6, impact_score=0.5, time_horizon="short_term",
        )


def test_classifier_passes_through_valid_event_type():
    result = NewsClassifier(provider=_StubProvider("earnings")).classify(
        title="x", content="y", candidate_stocks=[],
    )
    assert result.event_type == "earnings"


def test_classifier_normalizes_case_and_punctuation_variants():
    result = NewsClassifier(provider=_StubProvider("Profit-Warning")).classify(
        title="x", content="y", candidate_stocks=[],
    )
    assert result.event_type == "profit_warning"


def test_classifier_falls_back_to_other_for_unrecognized_type():
    result = NewsClassifier(provider=_StubProvider("not a real category")).classify(
        title="x", content="y", candidate_stocks=[],
    )
    assert result.event_type == "other"
    assert result.event_type in NEWS_EVENT_TYPES


# ── pipeline ──────────────────────────────────────────────────────────────────

def _seed_stocks(db):
    for sym, name in [("RELIANCE", "Reliance"), ("HDFCBANK", "HDFC Bank"), ("TCS", "TCS")]:
        db.add(m.Stock(symbol=sym, company_name=name))
    db.commit()


def test_pipeline_ingests_and_creates_events_and_stock_links(db_session):
    _seed_stocks(db_session)
    pipeline = NewsIngestionPipeline(provider=DemoNewsProvider())
    summary = pipeline.run_once(db_session, limit=20)

    assert summary["ingested"] == summary["events_created"] > 0
    assert summary["skipped_duplicate"] == 0

    reliance = db_session.query(m.Stock).filter_by(symbol="RELIANCE").one()
    linked_events = (
        db_session.query(m.StockEvent).filter(m.StockEvent.stock_id == reliance.id).all()
    )
    assert len(linked_events) >= 1


def test_pipeline_is_idempotent_on_rerun(db_session):
    _seed_stocks(db_session)
    pipeline = NewsIngestionPipeline(provider=DemoNewsProvider())
    first = pipeline.run_once(db_session, limit=20)
    second = pipeline.run_once(db_session, limit=20)

    assert second["ingested"] == 0
    assert second["skipped_duplicate"] == first["ingested"]
    assert db_session.query(m.NewsArticle).count() == first["ingested"]


def test_pipeline_skips_stock_events_for_unresolved_symbols(db_session):
    # No stocks seeded at all — articles still ingest, but no StockEvent rows
    # get created since nothing in the candidate/affected list resolves.
    pipeline = NewsIngestionPipeline(provider=DemoNewsProvider())
    summary = pipeline.run_once(db_session, limit=20)

    assert summary["ingested"] > 0
    assert db_session.query(m.StockEvent).count() == 0


def test_pipeline_preserves_source_attribution(db_session):
    item = RawNewsItem(
        source="Reuters", title="Test headline", url="https://example.com/a",
        published_at=datetime.now(timezone.utc), content="Reliance Industries did something notable.",
    )

    class _OneItemProvider:
        def get_latest_news(self, limit=20):
            return [item]

    _seed_stocks(db_session)
    pipeline = NewsIngestionPipeline(provider=_OneItemProvider())
    pipeline.run_once(db_session, limit=1)

    article = db_session.query(m.NewsArticle).one()
    assert article.source == "Reuters"
    assert article.url == "https://example.com/a"
