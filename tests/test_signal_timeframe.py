"""Tests for the intraday timeframe threading fix (docs/intraday_gaps.md
§5/§7 item 5): CompositeSignalEngine, latest_signal_per_stock, and
evaluate_alerts must all be able to distinguish daily from intraday
signals for the same stock — and must default to "1d" everywhere, so
running an intraday scoring pass never silently changes what the
existing daily-cadence Signals/Alerts/Portfolio Risk pages show."""
from __future__ import annotations
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.loader import Settings
from db.base import Base
from db import models as m
from signals.composite import CompositeSignalEngine
from signals.queries import latest_signal_per_stock
from signals.alerts import evaluate_alerts
from strategies.base import Signal as StrategySignal, SignalType


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class _StubMetaEngine:
    def __init__(self, signal):
        self._signal = signal

    def generate_signals(self, symbol, df):
        return [self._signal] if self._signal else []

    def best_signal(self, signals):
        return signals[0] if signals else None


def _make_df(n=60) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    dates = pd.date_range("2026-08-01", periods=n, freq="D", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0, 1.0, n))
    return pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": rng.integers(100_000, 200_000, n).astype(float),
    }, index=dates)


def _strategy_signal(price=100.0) -> StrategySignal:
    return StrategySignal(
        strategy="test_strategy", symbol="TEST", signal_type=SignalType.BUY,
        price=price, stop_loss=price - 4, take_profit=price + 6,
        confidence=0.8, timeframe="1d",
    )


# ── CompositeSignalEngine + persist ──────────────────────────────────────

def test_score_symbol_defaults_to_1d_timeframe(db_session):
    cfg = Settings().as_dict()
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(_strategy_signal()))
    scored = engine.score_symbol(db_session, "TEST", _make_df())
    assert scored.timeframe == "1d"


def test_score_symbol_accepts_explicit_intraday_timeframe(db_session):
    cfg = Settings().as_dict()
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(_strategy_signal()))
    scored = engine.score_symbol(db_session, "TEST", _make_df(), timeframe="15m")
    assert scored.timeframe == "15m"


def test_persist_stores_timeframe_on_signal_row(db_session):
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.commit()

    cfg = Settings().as_dict()
    engine = CompositeSignalEngine(cfg, meta_engine=_StubMetaEngine(_strategy_signal()))
    scored = engine.score_symbol(db_session, "TEST", _make_df(), timeframe="15m")
    row = engine.persist(db_session, scored)
    db_session.commit()

    assert row.timeframe == "15m"
    reloaded = db_session.query(m.Signal).filter(m.Signal.id == row.id).first()
    assert reloaded.timeframe == "15m"


# ── latest_signal_per_stock ───────────────────────────────────────────────

def _seed_signal(db, stock, *, timeframe, score, timestamp):
    db.add(m.Signal(
        stock_id=stock.id, timeframe=timeframe, direction=m.SignalDirection.BULLISH,
        score=score, confidence=80.0, timestamp=timestamp,
    ))


def test_latest_signal_per_stock_defaults_to_1d(db_session):
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.flush()
    now = datetime.now(timezone.utc)
    _seed_signal(db_session, stock, timeframe="1d", score=50.0, timestamp=now)
    _seed_signal(db_session, stock, timeframe="15m", score=99.0, timestamp=now)  # more recent-looking score, wrong timeframe
    db_session.commit()

    rows = latest_signal_per_stock(db_session).all()
    assert len(rows) == 1
    signal, symbol = rows[0]
    assert signal.timeframe == "1d"
    assert signal.score == 50.0


def test_latest_signal_per_stock_explicit_intraday_timeframe(db_session):
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.flush()
    now = datetime.now(timezone.utc)
    _seed_signal(db_session, stock, timeframe="1d", score=50.0, timestamp=now)
    _seed_signal(db_session, stock, timeframe="15m", score=99.0, timestamp=now)
    db_session.commit()

    rows = latest_signal_per_stock(db_session, timeframe="15m").all()
    assert len(rows) == 1
    signal, symbol = rows[0]
    assert signal.timeframe == "15m"
    assert signal.score == 99.0


def test_latest_signal_per_stock_multiple_stocks_each_own_timeframe_latest(db_session):
    s1 = m.Stock(symbol="AAA", company_name="A")
    s2 = m.Stock(symbol="BBB", company_name="B")
    db_session.add_all([s1, s2])
    db_session.flush()
    now = datetime.now(timezone.utc)
    _seed_signal(db_session, s1, timeframe="1d", score=10.0, timestamp=now)
    _seed_signal(db_session, s2, timeframe="1d", score=20.0, timestamp=now)
    _seed_signal(db_session, s1, timeframe="15m", score=999.0, timestamp=now)
    db_session.commit()

    rows = {symbol: signal.score for signal, symbol in latest_signal_per_stock(db_session).all()}
    assert rows == {"AAA": 10.0, "BBB": 20.0}


# ── evaluate_alerts ───────────────────────────────────────────────────────

def test_evaluate_alerts_defaults_to_1d_ignores_intraday_signal(db_session):
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.flush()
    now = datetime.now(timezone.utc)
    # Only an intraday signal clears the alert threshold; the 1d one doesn't.
    _seed_signal(db_session, stock, timeframe="1d", score=40.0, timestamp=now)
    _seed_signal(db_session, stock, timeframe="15m", score=95.0, timestamp=now)
    db_session.add(m.Alert(name="High score", condition={"score__gt": 80}, is_active=True))
    db_session.commit()

    summary = evaluate_alerts(db_session)  # default timeframe="1d"
    assert summary.triggers == []


def test_evaluate_alerts_explicit_intraday_timeframe_fires(db_session):
    stock = m.Stock(symbol="TEST", company_name="Test Co")
    db_session.add(stock)
    db_session.flush()
    now = datetime.now(timezone.utc)
    _seed_signal(db_session, stock, timeframe="1d", score=40.0, timestamp=now)
    _seed_signal(db_session, stock, timeframe="15m", score=95.0, timestamp=now)
    db_session.add(m.Alert(name="High score", condition={"score__gt": 80}, is_active=True))
    db_session.commit()

    summary = evaluate_alerts(db_session, timeframe="15m")
    assert len(summary.triggers) == 1
    assert summary.triggers[0].symbol == "TEST"
