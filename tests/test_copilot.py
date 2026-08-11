"""Tests for the Phase 6 AI market copilot."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai.schemas import CopilotAnswer
from db.base import Base
from db import models as m
from signals.copilot import CopilotIntent, _parse_intent, _retrieve, answer_query
from signals.queries import latest_signal_per_stock


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class _StubProvider:
    def __init__(self, answer: CopilotAnswer):
        self._answer = answer

    def complete_structured(self, *, system, prompt, schema):
        return self._answer


def _add_stock(db, symbol: str) -> m.Stock:
    stock = m.Stock(symbol=symbol, company_name=symbol.title())
    db.add(stock)
    db.flush()
    return stock


def _add_signal(db, stock, *, direction, score, volume_score, ts) -> m.Signal:
    sig = m.Signal(
        stock_id=stock.id, direction=direction, score=score, confidence=70.0,
        volume_score=volume_score, catalyst_score=0, technical_score=0,
        momentum_score=0, historical_score=50, regime_score=50, risk_score=50,
        timestamp=ts,
    )
    db.add(sig)
    db.flush()
    return sig


# ── intent routing (master-prompt example questions) ────────────────────────

@pytest.mark.parametrize("question,expected_type", [
    ("Which stocks have unusual volume today?", "unusual_volume"),
    ("Show bullish stocks with strong catalysts", "signals_filter"),
    ("Show me bearish setups", "signals_filter"),
    ("What are today's biggest market-moving events?", "news_recent"),
    ("What changed in the market since yesterday?", "unsupported"),
    ("Which sectors are strongest?", "unsupported"),
])
def test_parse_intent_matches_expected_type(question, expected_type):
    assert _parse_intent(question).query_type == expected_type


def test_parse_intent_extracts_symbol_for_why_questions():
    intent = _parse_intent("Why is Reliance moving?")
    assert intent.query_type == "why_moving"
    assert intent.symbol == "RELIANCE"


def test_parse_intent_bare_symbol_falls_back_to_why():
    intent = _parse_intent("Tell me about HDFC Bank")
    assert intent.query_type == "why_moving"
    assert intent.symbol == "HDFCBANK"


def test_parse_intent_no_symbol_no_keywords_is_unsupported():
    assert _parse_intent("What's the weather like").query_type == "unsupported"


# ── latest_signal_per_stock (regression for the recency-window bug) ─────────

def test_latest_signal_per_stock_regression_uneven_rescoring(db_session):
    """Reproduces the exact bug found in live verification: some stocks
    get re-scored later than others, and a naive "top-N-by-timestamp then
    dedup" approach silently drops stocks whose latest row isn't near the
    top. The fix must return exactly one row per stock — its true latest
    — regardless of how re-scoring is distributed in time."""
    now = datetime.now(timezone.utc)

    # 5 stocks scored together, long ago.
    old_stocks = [_add_stock(db_session, f"OLD{i}") for i in range(5)]
    for i, stock in enumerate(old_stocks):
        _add_signal(
            db_session, stock, direction=m.SignalDirection.NO_SIGNAL, score=10,
            volume_score=90.0, ts=now - timedelta(hours=2, minutes=i),
        )

    # 1 stock re-scored much more recently — must not push the others out.
    recent_stock = _add_stock(db_session, "RECENT1")
    _add_signal(
        db_session, recent_stock, direction=m.SignalDirection.NO_SIGNAL, score=20,
        volume_score=10.0, ts=now,
    )
    db_session.commit()

    rows = latest_signal_per_stock(db_session).all()
    symbols = {sym for _, sym in rows}
    assert symbols == {"OLD0", "OLD1", "OLD2", "OLD3", "OLD4", "RECENT1"}


def test_latest_signal_per_stock_picks_the_true_latest_row(db_session):
    stock = _add_stock(db_session, "TEST")
    now = datetime.now(timezone.utc)
    _add_signal(db_session, stock, direction=m.SignalDirection.BULLISH, score=50,
                volume_score=10.0, ts=now - timedelta(hours=1))
    _add_signal(db_session, stock, direction=m.SignalDirection.BEARISH, score=90,
                volume_score=99.0, ts=now)
    db_session.commit()

    rows = latest_signal_per_stock(db_session).all()
    assert len(rows) == 1
    signal, symbol = rows[0]
    assert symbol == "TEST"
    assert signal.direction == m.SignalDirection.BEARISH
    assert signal.score == 90


# ── retrieval ─────────────────────────────────────────────────────────────

def test_retrieve_unusual_volume_only_above_threshold(db_session):
    now = datetime.now(timezone.utc)
    high = _add_stock(db_session, "HIGHVOL")
    low = _add_stock(db_session, "LOWVOL")
    _add_signal(db_session, high, direction=m.SignalDirection.NO_SIGNAL, score=10,
                volume_score=90.0, ts=now)
    _add_signal(db_session, low, direction=m.SignalDirection.NO_SIGNAL, score=10,
                volume_score=20.0, ts=now)
    db_session.commit()

    data, evidence = _retrieve(db_session, CopilotIntent("unusual_volume"))
    symbols = {s["symbol"] for s in data["unusual_volume_signals"]}
    assert symbols == {"HIGHVOL"}
    assert any("HIGHVOL" in e for e in evidence)


def test_retrieve_signals_filter_by_direction(db_session):
    now = datetime.now(timezone.utc)
    bull = _add_stock(db_session, "BULL1")
    bear = _add_stock(db_session, "BEAR1")
    _add_signal(db_session, bull, direction=m.SignalDirection.BULLISH, score=80,
                volume_score=10.0, ts=now)
    _add_signal(db_session, bear, direction=m.SignalDirection.BEARISH, score=80,
                volume_score=10.0, ts=now)
    db_session.commit()

    data, _ = _retrieve(db_session, CopilotIntent("signals_filter", direction="bullish"))
    assert [s["symbol"] for s in data["signals"]] == ["BULL1"]


def test_retrieve_why_moving_unknown_symbol_returns_empty(db_session):
    data, evidence = _retrieve(db_session, CopilotIntent("why_moving", symbol="NOTREAL"))
    assert data == {}
    assert evidence == []


def test_retrieve_no_data_returns_empty(db_session):
    data, evidence = _retrieve(db_session, CopilotIntent("unusual_volume"))
    assert data == {}
    assert evidence == []


# ── full answer_query flow ───────────────────────────────────────────────

def test_answer_query_unsupported_short_circuits_before_llm(db_session):
    result = answer_query(db_session, "What's the weather like")
    assert result.insufficient_evidence is True
    assert "why a stock is moving" in result.answer


def test_answer_query_no_matching_data_is_insufficient_evidence(db_session):
    result = answer_query(db_session, "Which stocks have unusual volume today?")
    assert result.insufficient_evidence is True
    assert result.evidence == []


def test_answer_query_grounds_llm_prompt_in_retrieved_data(db_session):
    now = datetime.now(timezone.utc)
    stock = _add_stock(db_session, "HIGHVOL")
    _add_signal(db_session, stock, direction=m.SignalDirection.NO_SIGNAL, score=10,
                volume_score=95.0, ts=now)
    db_session.commit()

    captured_prompt = {}

    class _CapturingProvider(_StubProvider):
        def complete_structured(self, *, system, prompt, schema):
            captured_prompt["text"] = prompt
            return self._answer

    stub = _CapturingProvider(CopilotAnswer(
        answer="HIGHVOL shows unusually high volume.", confidence="high",
        evidence=["Signal for HIGHVOL: volume_score=95.0"], insufficient_evidence=False,
    ))
    result = answer_query(db_session, "Which stocks have unusual volume today?", provider=stub)

    assert "HIGHVOL" in captured_prompt["text"]
    assert result.insufficient_evidence is False
    assert result.answer == "HIGHVOL shows unusually high volume."
