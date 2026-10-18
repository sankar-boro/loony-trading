"""
Composite (DB-backed, multi-factor) signals — distinct from the ad-hoc
live scanner in routers/signals.py. This is the persisted, explainable
output of signals.CompositeSignalEngine (Phase 2).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.base import get_db
from db.models import Signal, SignalDirection, Stock, TradeSetup
from signals.historical import find_analogues
from signals.queries import latest_signal_per_stock
from signals.why import explain_move

router = APIRouter()


def _trade_setup_dict(db: Session, signal_id: int) -> dict | None:
    ts = db.query(TradeSetup).filter(TradeSetup.signal_id == signal_id).first()
    if not ts:
        return None
    return {
        "entry_low": ts.entry_low, "entry_high": ts.entry_high,
        "stop_loss": ts.stop_loss, "target_1": ts.target_1, "target_2": ts.target_2,
        "risk_reward": ts.risk_reward,
    }


def _signal_dict(db: Session, signal: Signal, symbol: str, with_setup: bool = True) -> dict:
    return {
        "id": signal.id,
        "symbol": symbol,
        "timeframe": signal.timeframe,
        "timestamp": signal.timestamp.isoformat(),
        "direction": signal.direction.value,
        "score": signal.score,
        "confidence": signal.confidence,
        "components": {
            "catalyst": signal.catalyst_score,
            "technical": signal.technical_score,
            "momentum": signal.momentum_score,
            "volume": signal.volume_score,
            "historical": signal.historical_score,
            "regime": signal.regime_score,
            "risk": signal.risk_score,
        },
        "explanation": signal.explanation,
        "trade_setup": _trade_setup_dict(db, signal.id) if with_setup else None,
    }


@router.get("/signals/composite")
def list_composite_signals(
    direction: str | None = Query(None, description="bullish|bearish|watch|no_signal"),
    symbol: str | None = None,
    timeframe: str = Query("1d", description='bar size, e.g. "1d", "30m", "1h"'),
    latest_only: bool = Query(True, description="one row per stock — its most recent signal"),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    if latest_only:
        q = latest_signal_per_stock(db, timeframe=timeframe)
    else:
        q = (
            db.query(Signal, Stock.symbol)
            .join(Stock, Signal.stock_id == Stock.id)
            .filter(Signal.timeframe == timeframe)
        )

    if direction:
        try:
            q = q.filter(Signal.direction == SignalDirection(direction.lower()))
        except ValueError:
            raise HTTPException(400, f"Invalid direction: {direction}")
    if symbol:
        q = q.filter(Stock.symbol == symbol.upper())

    rows = q.order_by(desc(Signal.timestamp)).limit(limit).all()
    return [_signal_dict(db, signal, sym, with_setup=False) for signal, sym in rows]


class IntradayScanRequest(BaseModel):
    symbols: list[str] = []          # empty = whole universe, capped by `limit`
    limit: int | None = 5            # ignored when `symbols` is non-empty
    lookback_days: int = 5
    timeframe: str = "30m"           # not "15m" — see config/settings.yaml's note
                                      # on Upstox returning HTTP 400 for 5m/15m here


@router.post("/signals/intraday-scan")
def run_intraday_scan(req: IntradayScanRequest) -> dict:
    """UI-triggered version of `scripts/run_signal_engine.py --timeframe
    30m` (docs/appendix/intraday-audit.md §5/§7 item 5) — same function, same
    Signal rows tagged with this timeframe, just reachable from a button
    instead of a terminal. Runs synchronously in FastAPI's threadpool
    (this is a plain `def` route, not `async def`), which is fine for the
    small symbol counts this form is meant for."""
    from scripts.run_signal_engine import run_signal_engine
    return run_signal_engine(
        limit=req.limit, lookback_days=req.lookback_days,
        timeframe=req.timeframe, symbols=req.symbols or None,
    )


@router.get("/signals/performance")
def get_signal_performance(days: int = Query(90, ge=7, le=365), db: Session = Depends(get_db)) -> dict:
    """How past composite signals did: forward returns and setup results by
    direction, score band and component (signals/outcomes.py)."""
    from signals.outcomes import performance
    return performance(db, days=days)


@router.get("/signals/composite/{signal_id}")
def get_composite_signal(signal_id: int, db: Session = Depends(get_db)) -> dict:
    row = (
        db.query(Signal, Stock.symbol)
        .join(Stock, Signal.stock_id == Stock.id)
        .filter(Signal.id == signal_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Signal not found")
    signal, symbol = row
    return _signal_dict(db, signal, symbol, with_setup=True)


@router.get("/historical-analogues")
def get_historical_analogues(
    event_type: str,
    direction: str | None = None,
    symbol: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Historical analysis, not a prediction (spec §22) — win-rate and
    median return of *past* events sharing this event_type, never a
    forecast of what this stock will do next."""
    stock_id = None
    if symbol:
        stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
        if not stock:
            raise HTTPException(404, f"Unknown symbol: {symbol}")
        stock_id = stock.id

    result = find_analogues(db, event_type=event_type, direction=direction, stock_id=stock_id)
    return {
        "event_type": result.event_type,
        "direction": result.direction,
        "total_samples": result.total_samples,
        "label": "Historical analysis of past events — not a prediction",
        "horizons": [
            {
                "horizon": h.horizon, "sample_count": h.sample_count,
                "win_rate_pct": h.win_rate_pct, "median_return_pct": h.median_return_pct,
            }
            for h in result.horizons
        ],
    }


@router.get("/stocks/{symbol}/why")
def why_is_it_moving(symbol: str, db: Session = Depends(get_db)) -> dict:
    """The flagship explainability feature (spec §27) — see signals/why.py
    for the actual logic, shared with the Phase 6 copilot."""
    result = explain_move(db, symbol)
    if result is None:
        raise HTTPException(404, f"Unknown symbol: {symbol}")
    return result
