"""Signal outcomes (signals/outcomes.py): forward returns, setup results,
setup invalidation, and the performance report."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base, get_db
from db.models import Signal, SignalDirection, SignalOutcome, Stock, TradeSetup
from signals.outcomes import evaluate, performance, update_outcomes

NOW = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def Session():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _bars(closes, start="2026-01-01") -> pd.DataFrame:
    """Daily bars stamped like Upstox (IST midnight)."""
    idx = pd.date_range(start, periods=len(closes), freq="D", tz="Asia/Kolkata")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000.0})


def _sig(db, stock, ts, direction=SignalDirection.BULLISH, score=75.0, setup=None, **comp):
    s = Signal(stock_id=stock.id, timestamp=ts, timeframe="1d", direction=direction,
               score=score, confidence=70, **comp)
    db.add(s)
    db.flush()
    if setup:
        db.add(TradeSetup(signal_id=s.id, entry_low=0, entry_high=0, stop_loss=setup[0], target_1=setup[1]))
    db.flush()
    return s


def test_evaluate_returns_and_setup_walk():
    bars = _bars([100, 101, 103, 99, 110] + [110] * 30)
    bars.index = [d.date().isoformat() for d in bars.index]
    setup = TradeSetup(stop_loss=97.0, target_1=109.0)
    out = evaluate(SignalDirection.BULLISH, "2026-01-01", bars, setup)
    assert out["entry_price"] == 100
    assert out["ret_1d"] == pytest.approx(0.01) and out["ret_5d"] == pytest.approx(0.10)
    assert out["setup_result"] == "target" and out["setup_bars"] == 4     # high 111 on day 4
    assert out["complete"]
    bear = evaluate(SignalDirection.BEARISH, "2026-01-01", bars, TradeSetup(stop_loss=104.0, target_1=95.0))
    assert bear["setup_result"] == "stop"                                  # high 111 ≥ 104
    assert evaluate(SignalDirection.BULLISH, "2025-12-31", bars) is None   # day not in bars


def test_update_outcomes_end_to_end(Session):
    db = Session()
    tcs = Stock(symbol="TCS", company_name="TCS")
    db.add(tcs)
    db.flush()
    morning = _sig(db, tcs, datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc), score=60)
    last = _sig(db, tcs, datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc), setup=(97.0, 109.0))
    _sig(db, tcs, datetime(2026, 3, 20, 5, 0, tzinfo=timezone.utc))            # today: too early
    db.commit()

    calls = []

    def fetch(symbols, days):
        calls.append((symbols, days))
        return {"TCS": _bars([100, 101, 103, 99, 110] + [110] * 30)}

    summary = update_outcomes(db, fetch, now=NOW, max_age_days=120)
    db.commit()
    assert summary == {"pending": 1, "updated": 1, "completed": 1}
    [o] = db.scalars(select(SignalOutcome)).all()
    assert o.signal_id == last.id and o.signal_id != morning.id               # last signal of the day
    assert o.signal_date == "2026-01-01" and o.setup_result == "target" and o.complete
    assert db.get(Signal, last.id).status == "closed"
    assert calls[0][0] == ["TCS"]
    assert update_outcomes(db, fetch, now=NOW, max_age_days=120)["pending"] == 0   # complete: not redone


def test_stop_invalidates_setup_and_incomplete_rows_are_refreshed(Session):
    db = Session()
    st = Stock(symbol="SBIN", company_name="SBI")
    db.add(st)
    db.flush()
    s = _sig(db, st, datetime(2026, 3, 9, 9, 0, tzinfo=timezone.utc), setup=(95.0, 130.0))
    db.commit()
    short = _bars([100, 99, 94, 96], start="2026-03-09")                       # stop hit, only 3 bars after
    update_outcomes(db, lambda syms, d: {"SBIN": short}, now=NOW)
    db.commit()
    o = db.scalar(select(SignalOutcome))
    assert o.setup_result == "stop" and o.ret_1d == pytest.approx(-0.01)
    assert o.ret_20d is None and not o.complete
    assert db.scalar(select(TradeSetup)).invalidated_at is not None
    assert db.get(Signal, s.id).status == "invalidated"
    longer = _bars([100, 99, 94, 96] + [97] * 25, start="2026-03-09")
    update_outcomes(db, lambda syms, d: {"SBIN": longer}, now=datetime(2026, 4, 30, tzinfo=timezone.utc))
    db.commit()
    o = db.scalar(select(SignalOutcome))
    assert o.ret_20d == pytest.approx(-0.03) and o.complete


def _seed_outcomes(db, base: datetime = datetime(2026, 3, 1, 9, tzinfo=timezone.utc)):
    st = Stock(symbol="X", company_name="X")
    db.add(st)
    db.flush()
    rows = [(SignalDirection.BULLISH, 82, 0.04, 70), (SignalDirection.BULLISH, 65, -0.01, 40),
            (SignalDirection.BEARISH, 78, -0.03, 75), (SignalDirection.NO_SIGNAL, 40, 0.01, 50)]
    for i, (d, score, r5, tech) in enumerate(rows):
        ts = base + timedelta(days=i)
        s = _sig(db, st, ts, direction=d, score=score, technical_score=tech)
        db.add(SignalOutcome(signal_id=s.id, signal_date=ts.date().isoformat(), entry_price=100,
                             ret_1d=r5 / 2, ret_5d=r5, ret_20d=r5, complete=True,
                             setup_result="target" if r5 * (1 if d != SignalDirection.BEARISH else -1) > 0 else "stop"))
    db.commit()


def test_performance_report(Session):
    db = Session()
    _seed_outcomes(db)
    p = performance(db, days=90, now=NOW)
    by = {d["direction"]: d for d in p["by_direction"]}
    assert p["evaluated"] == 4
    assert p["baseline"]["ret_5d"] == pytest.approx(0.25)                       # mean of 4, -1, -3, 1 (%)
    assert by["bullish"]["avg_5d"] == pytest.approx(1.5) and by["bullish"]["hit_5d"] == 50.0
    assert by["bearish"]["avg_5d"] == pytest.approx(3.0)                        # a fall is a win
    assert by["bearish"]["excess_5d"] == pytest.approx(3.0 + 0.25)
    assert by["no_signal"]["hit_5d"] is None
    assert by["bullish"]["setups"]["target"] == 1
    assert {r["band"] for r in p["by_score"]} == {"60-70", "70-80", "80-90"}


def test_performance_endpoint(Session):
    from dashboard.backend.routers.composite_signals import router
    db = Session()
    _seed_outcomes(db, base=datetime.now(timezone.utc) - timedelta(days=20))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: Session()
    r = TestClient(app).get("/api/signals/performance?days=30")
    assert r.status_code == 200 and r.json()["evaluated"] == 4
