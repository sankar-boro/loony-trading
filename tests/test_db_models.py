"""
Structural tests for the Phase 0 persistence layer.

Runs against an in-memory SQLite engine bound to the same Base.metadata as
production (db.base.Base) — not against db.base.engine itself, which is
hardcoded to Postgres for the docker-compose/local-dev path. Column types
in db/models.py are deliberately portable (generic JSON/Enum, no JSONB) so
this works without a running Postgres instance.
"""
from __future__ import annotations
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db import models as m


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_all_tables_succeed(db_session):
    # fixture setup already ran create_all(); a trivial query per table
    # confirms every model in db/models.py mapped cleanly.
    for model in (
        m.Stock, m.PriceBar, m.NewsArticle, m.NewsEvent, m.StockEvent,
        m.Signal, m.TradeSetup, m.HistoricalEvent, m.Watchlist,
        m.WatchlistItem, m.Alert,
    ):
        assert db_session.query(model).count() == 0


def test_stock_symbol_unique(db_session):
    db_session.add(m.Stock(symbol="RELIANCE", company_name="Reliance Industries"))
    db_session.commit()
    db_session.add(m.Stock(symbol="RELIANCE", company_name="Duplicate"))
    with pytest.raises(Exception):
        db_session.commit()


def test_signal_and_trade_setup_relationship(db_session):
    stock = m.Stock(symbol="TCS", company_name="Tata Consultancy Services")
    db_session.add(stock)
    db_session.flush()

    signal = m.Signal(
        stock_id=stock.id,
        direction=m.SignalDirection.BULLISH,
        score=82.0,
        confidence=76.0,
        catalyst_score=22,
        technical_score=17,
        explanation={"catalyst": 22, "technical": 17},
    )
    db_session.add(signal)
    db_session.flush()

    setup = m.TradeSetup(
        signal_id=signal.id,
        entry_low=3400.0,
        entry_high=3420.0,
        stop_loss=3350.0,
        target_1=3500.0,
        risk_reward=2.0,
    )
    db_session.add(setup)
    db_session.commit()

    fetched = db_session.query(m.Signal).one()
    assert fetched.direction == m.SignalDirection.BULLISH
    assert fetched.explanation == {"catalyst": 22, "technical": 17}


def test_watchlist_item_prevents_duplicate_stock(db_session):
    stock = m.Stock(symbol="INFY", company_name="Infosys")
    watchlist = m.Watchlist(name="My Stocks")
    db_session.add_all([stock, watchlist])
    db_session.flush()

    db_session.add(m.WatchlistItem(watchlist_id=watchlist.id, stock_id=stock.id))
    db_session.commit()

    db_session.add(m.WatchlistItem(watchlist_id=watchlist.id, stock_id=stock.id))
    with pytest.raises(Exception):
        db_session.commit()


def test_price_bar_unique_constraint(db_session):
    stock = m.Stock(symbol="HDFCBANK", company_name="HDFC Bank")
    db_session.add(stock)
    db_session.flush()

    ts = datetime(2026, 8, 10, 9, 15, tzinfo=timezone.utc)
    db_session.add(m.PriceBar(stock_id=stock.id, timestamp=ts, timeframe="1d",
                               open=100, high=105, low=99, close=104, volume=1000))
    db_session.commit()

    db_session.add(m.PriceBar(stock_id=stock.id, timestamp=ts, timeframe="1d",
                               open=100, high=105, low=99, close=104, volume=1000))
    with pytest.raises(Exception):
        db_session.commit()
