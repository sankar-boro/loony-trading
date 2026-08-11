"""Tests for the Phase 2 composite multi-factor signal engine."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.loader import Settings
from db.base import Base
from db import models as m
from signals.composite import CompositeSignalEngine
from strategies.base import Signal as StrategySignal, SignalType


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def cfg():
    return Settings().as_dict()


def _make_df(n=250, trend=0.0, vol_spike=False, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    close = 100 + np.cumsum(rng.normal(trend, 1.0, n))
    volume = rng.integers(100_000, 200_000, n).astype(float)
    if vol_spike:
        volume[-1] = volume[-20:-1].mean() * 3
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.3, n),
        "high": close + abs(rng.normal(0, 1.0, n)),
        "low": close - abs(rng.normal(0, 1.0, n)),
        "close": close,
        "volume": volume,
    }, index=dates)


class _StubMetaEngine:
    """Duck-types MetaStrategyEngine so tests control the winning signal
    directly instead of depending on real strategies firing."""

    def __init__(self, signal: StrategySignal | None):
        self._signal = signal

    def generate_signals(self, symbol, df):
        return [self._signal] if self._signal else []

    def best_signal(self, signals):
        return signals[0] if signals else None


def _strategy_signal(confidence=0.8, price=100.0, direction=SignalType.BUY) -> StrategySignal:
    return StrategySignal(
        strategy="test_strategy", symbol="TEST", signal_type=direction,
        price=price, stop_loss=price - 4, take_profit=price + 6,
        confidence=confidence, timeframe="1d",
    )


# ── component-level ──────────────────────────────────────────────────────────

def test_momentum_component_zero_on_insufficient_data(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    assert engine._momentum_component(pd.DataFrame({"close": [1, 2, 3]})) == 0.0


def test_volume_component_scales_with_relative_volume(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    flat_df = _make_df(vol_spike=False)
    spike_df = _make_df(vol_spike=True)
    assert engine._volume_component(spike_df) > engine._volume_component(flat_df)


def test_risk_component_penalizes_high_volatility(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    calm = _make_df(seed=1)
    # Manually widen the range to simulate a volatile instrument.
    volatile = calm.copy()
    volatile["high"] = volatile["close"] * 1.05
    volatile["low"] = volatile["close"] * 0.95
    assert engine._risk_component(volatile) < engine._risk_component(calm)


def test_catalyst_component_no_recent_event_returns_zero(db_session, cfg):
    db_session.add(m.Stock(symbol="RELIANCE", company_name="Reliance"))
    db_session.commit()
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    score, direction, event_type = engine._catalyst_component(db_session, "RELIANCE")
    assert score == 0.0
    assert direction is None


def test_catalyst_component_uses_recent_event(db_session, cfg):
    stock = m.Stock(symbol="RELIANCE", company_name="Reliance")
    db_session.add(stock)
    db_session.flush()
    article = m.NewsArticle(
        source="Test", title="t", url="http://x", published_at=datetime.now(timezone.utc),
        hash="abc123",
    )
    db_session.add(article)
    db_session.flush()
    event = m.NewsEvent(
        article_id=article.id, event_type="earnings", impact_score=0.8,
        catalyst_score=9.0, sentiment_score=0.7, confidence=0.9,
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(m.StockEvent(
        stock_id=stock.id, event_id=event.id, relevance_score=1.0, direction="bullish",
    ))
    db_session.commit()

    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    score, direction, event_type = engine._catalyst_component(db_session, "RELIANCE")
    assert score == pytest.approx(90.0)  # 9.0 * 10 * relevance 1.0
    assert direction == "bullish"


def test_catalyst_component_ignores_stale_event(db_session, cfg):
    stock = m.Stock(symbol="RELIANCE", company_name="Reliance")
    db_session.add(stock)
    db_session.flush()
    article = m.NewsArticle(
        source="Test", title="t", url="http://x",
        published_at=datetime.now(timezone.utc) - timedelta(days=10), hash="old1",
    )
    db_session.add(article)
    db_session.flush()
    event = m.NewsEvent(
        article_id=article.id, event_type="earnings", impact_score=0.8,
        catalyst_score=9.0, sentiment_score=0.7, confidence=0.9,
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db_session.add(event)
    db_session.flush()
    old_stock_event = m.StockEvent(
        stock_id=stock.id, event_id=event.id, relevance_score=1.0, direction="bullish",
    )
    old_stock_event.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    db_session.add(old_stock_event)
    db_session.commit()

    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    score, direction, event_type = engine._catalyst_component(db_session, "RELIANCE")
    assert score == 0.0
    assert direction is None


# ── classification / quality gate ────────────────────────────────────────────

def test_classify_no_signal_when_no_strategy_fires(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    direction, confidence = engine._classify(None, total=95.0, direction_hint=0)
    assert direction == m.SignalDirection.NO_SIGNAL
    assert confidence == 0.0


def test_classify_bullish_when_score_and_confidence_clear_gate(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    best = _strategy_signal(confidence=0.9)
    direction, confidence = engine._classify(best, total=80.0, direction_hint=1)
    assert direction == m.SignalDirection.BULLISH
    assert confidence == 90.0


def test_classify_bearish_direction_follows_hint(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    best = _strategy_signal(confidence=0.9, direction=SignalType.SELL)
    direction, _ = engine._classify(best, total=80.0, direction_hint=-1)
    assert direction == m.SignalDirection.BEARISH


def test_classify_watch_below_gate_above_watch_threshold(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    best = _strategy_signal(confidence=0.55)
    direction, _ = engine._classify(best, total=55.0, direction_hint=1)
    assert direction == m.SignalDirection.WATCH


def test_classify_no_signal_below_watch_threshold(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    best = _strategy_signal(confidence=0.3)
    direction, _ = engine._classify(best, total=20.0, direction_hint=1)
    assert direction == m.SignalDirection.NO_SIGNAL


def test_classify_clamps_confidence_above_100(cfg):
    # Regression: a strategy returning confidence > 1.0 (out-of-contract)
    # must not push displayed confidence past 100.
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    best = _strategy_signal(confidence=1.5)
    direction, confidence = engine._classify(best, total=90.0, direction_hint=1)
    assert confidence == 100.0
    assert direction == m.SignalDirection.BULLISH


# ── full score_symbol + persist round trip ───────────────────────────────────

def test_score_symbol_no_strategy_signal_is_no_signal_with_zero_confidence(db_session, cfg):
    db_session.add(m.Stock(symbol="TEST", company_name="Test Co"))
    db_session.commit()
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    scored = engine.score_symbol(db_session, "TEST", _make_df())
    assert scored.direction == m.SignalDirection.NO_SIGNAL
    assert scored.confidence == 0.0
    assert scored.stop_loss is None  # no trade setup without an actionable direction


def test_score_symbol_persists_all_seven_components(db_session, cfg):
    db_session.add(m.Stock(symbol="TEST", company_name="Test Co"))
    db_session.commit()
    best = _strategy_signal(confidence=0.85, price=100.0)
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(best))

    scored = engine.score_symbol(db_session, "TEST", _make_df(trend=0.3))
    signal = engine.persist(db_session, scored)
    db_session.commit()

    assert signal is not None
    assert set(scored.components.keys()) == {
        "catalyst", "technical", "momentum", "volume", "historical", "regime", "risk",
    }
    fetched = db_session.query(m.Signal).filter_by(id=signal.id).one()
    assert fetched.explanation == scored.components
    for key in scored.components:
        assert getattr(fetched, f"{key}_score") == scored.components[key]


def test_score_symbol_attaches_trade_setup_when_actionable(db_session, cfg):
    db_session.add(m.Stock(symbol="TEST", company_name="Test Co"))
    db_session.commit()
    best = _strategy_signal(confidence=0.95, price=100.0)
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(best))
    # Force the gate open regardless of the other components' real values.
    engine.gate = {"min_score": 0, "min_confidence": 0, "watch_score": 0}

    scored = engine.score_symbol(db_session, "TEST", _make_df(trend=0.3))
    assert scored.direction == m.SignalDirection.BULLISH
    assert scored.stop_loss == pytest.approx(96.0)
    assert scored.target_1 == pytest.approx(106.0)
    assert scored.risk_reward == pytest.approx(1.5)

    signal = engine.persist(db_session, scored)
    db_session.commit()
    trade_setup = db_session.query(m.TradeSetup).filter_by(signal_id=signal.id).one()
    assert trade_setup.stop_loss == pytest.approx(96.0)


# ── historical analogue integration (Phase 3) ────────────────────────────────

def _seed_historical_events(db, event_type: str, outcomes: list[float], stock_id: int) -> None:
    """outcomes are 1d percent returns; price_before is fixed at 100 so
    price_after_1d = 100 * (1 + r/100) reproduces the return exactly."""
    for i, r in enumerate(outcomes):
        db.add(m.HistoricalEvent(
            stock_id=stock_id, event_type=event_type,
            event_timestamp=datetime.now(timezone.utc) - timedelta(days=i + 1),
            direction="bullish", price_before=100.0, price_after_1d=100.0 * (1 + r / 100),
        ))
    db.commit()


def test_historical_component_neutral_without_event_type(cfg):
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    assert engine._historical_component(None, None, None) == 50.0


def test_historical_component_neutral_below_min_samples(db_session, cfg):
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.commit()
    _seed_historical_events(db_session, "earnings", [1.0, 2.0], stock.id)  # only 2, below min 5

    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    assert engine._historical_component(db_session, "earnings", "bullish") == 50.0


def test_historical_component_uses_real_win_rate_with_enough_samples(db_session, cfg):
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.commit()
    # 8 samples, 6 winners (positive 1d return) -> 75% win rate, hand-verifiable.
    outcomes = [1.0, 2.0, 0.5, -1.0, 3.0, -0.5, 1.5, 0.8]
    _seed_historical_events(db_session, "earnings", outcomes, stock.id)

    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(None))
    score = engine._historical_component(db_session, "earnings", "bullish")
    assert score == pytest.approx(75.0)


def test_find_analogues_reports_sample_count_and_median(db_session):
    from signals.historical import find_analogues

    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.commit()
    outcomes = [1.0, 2.0, 0.5, -1.0, 3.0, -0.5, 1.5, 0.8]
    _seed_historical_events(db_session, "earnings", outcomes, stock.id)

    result = find_analogues(db_session, event_type="earnings")
    assert result.total_samples == 8
    day_1 = next(h for h in result.horizons if h.horizon == "1d")
    assert day_1.sample_count == 8
    assert day_1.win_rate_pct == pytest.approx(75.0)
    assert day_1.median_return_pct == pytest.approx(0.9)  # median of the sorted outcomes

    fifteen_min = next(h for h in result.horizons if h.horizon == "15m")
    assert fifteen_min.sample_count == 0
    assert fifteen_min.win_rate_pct is None


def test_find_analogues_filters_by_direction(db_session):
    from signals.historical import find_analogues

    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.commit()
    db_session.add(m.HistoricalEvent(
        stock_id=stock.id, event_type="earnings", event_timestamp=datetime.now(timezone.utc),
        direction="bearish", price_before=100.0, price_after_1d=95.0,
    ))
    db_session.commit()

    bullish_result = find_analogues(db_session, event_type="earnings", direction="bullish")
    assert bullish_result.total_samples == 0

    bearish_result = find_analogues(db_session, event_type="earnings", direction="bearish")
    assert bearish_result.total_samples == 1
