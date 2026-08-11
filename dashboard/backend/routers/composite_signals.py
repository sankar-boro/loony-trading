"""
Composite (DB-backed, multi-factor) signals — distinct from the ad-hoc
live scanner in routers/signals.py. This is the persisted, explainable
output of signals.CompositeSignalEngine (Phase 2).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.base import get_db
from db.models import NewsArticle, NewsEvent, Signal, SignalDirection, Stock, StockEvent, TradeSetup
from signals.historical import find_analogues

router = APIRouter()

_WHY_NEWS_LOOKBACK = timedelta(days=7)
_COMPONENT_LABEL = {
    "catalyst": "News catalyst", "technical": "Technical setup", "momentum": "Price momentum",
    "volume": "Volume activity", "historical": "Historical analogue", "regime": "Market regime",
    "risk": "Volatility/risk profile",
}
_WEIGHTS = {
    "catalyst": 0.25, "technical": 0.20, "momentum": 0.15, "volume": 0.15,
    "historical": 0.10, "regime": 0.10, "risk": 0.05,
}


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
    latest_only: bool = Query(True, description="one row per stock — its most recent signal"),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = db.query(Signal, Stock.symbol).join(Stock, Signal.stock_id == Stock.id)

    if direction:
        try:
            q = q.filter(Signal.direction == SignalDirection(direction.lower()))
        except ValueError:
            raise HTTPException(400, f"Invalid direction: {direction}")
    if symbol:
        q = q.filter(Stock.symbol == symbol.upper())

    q = q.order_by(desc(Signal.timestamp))
    rows = q.limit(limit * 3 if latest_only else limit).all()

    if latest_only:
        seen: set[int] = set()
        deduped = []
        for signal, sym in rows:
            if signal.stock_id in seen:
                continue
            seen.add(signal.stock_id)
            deduped.append((signal, sym))
            if len(deduped) >= limit:
                break
        rows = deduped

    return [_signal_dict(db, signal, sym, with_setup=False) for signal, sym in rows]


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
    """The flagship explainability feature (spec §27): fuse the latest
    persisted composite score, recent news, and historical analogues into
    one evidence-backed explanation. Every claim traces to a DB row —
    if there's nothing to point at, this says so rather than guessing."""
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    if not stock:
        raise HTTPException(404, f"Unknown symbol: {symbol}")

    latest_signal = (
        db.query(Signal)
        .filter(Signal.stock_id == stock.id)
        .order_by(desc(Signal.timestamp))
        .first()
    )

    since = datetime.now(timezone.utc) - _WHY_NEWS_LOOKBACK
    news_rows = (
        db.query(StockEvent, NewsEvent, NewsArticle)
        .join(NewsEvent, StockEvent.event_id == NewsEvent.id)
        .join(NewsArticle, NewsEvent.article_id == NewsArticle.id)
        .filter(StockEvent.stock_id == stock.id, StockEvent.created_at >= since)
        .order_by(desc(StockEvent.created_at))
        .limit(10)
        .all()
    )
    recent_news = [
        {
            "headline": article.title, "source": article.source, "url": article.url,
            "published_at": article.published_at.isoformat(), "event_type": news_event.event_type,
            "sentiment_score": news_event.sentiment_score, "impact_score": news_event.impact_score,
            "summary": news_event.summary,
        }
        for _, news_event, article in news_rows
    ]

    drivers: list[dict] = []
    if latest_signal and latest_signal.explanation:
        ranked = sorted(
            latest_signal.explanation.items(),
            key=lambda kv: kv[1] * _WEIGHTS.get(kv[0], 0), reverse=True,
        )
        for key, value in ranked:
            if value <= 0:
                continue
            drivers.append({
                "factor": key, "label": _COMPONENT_LABEL.get(key, key),
                "score": value, "weight": _WEIGHTS.get(key, 0),
                "contribution": round(value * _WEIGHTS.get(key, 0), 1),
            })

    historical_analogue = None
    if news_rows:
        top_event_type = news_rows[0][1].event_type
        top_direction = news_rows[0][0].direction
        result = find_analogues(db, event_type=top_event_type, direction=top_direction)
        day_1 = next((h for h in result.horizons if h.horizon == "1d"), None)
        if day_1 and day_1.sample_count > 0:
            historical_analogue = {
                "event_type": top_event_type, "direction": top_direction,
                "sample_count": day_1.sample_count, "win_rate_pct": day_1.win_rate_pct,
                "median_return_pct": day_1.median_return_pct,
                "label": "Historical analysis of past events — not a prediction",
            }

    if not latest_signal and not recent_news:
        conclusion = f"No scored signal or recent news found for {stock.symbol}. Insufficient evidence."
    elif drivers:
        top = drivers[0]
        conclusion = (
            f"The move appears primarily driven by {top['label'].lower()} "
            f"(contributing {top['contribution']} of the {latest_signal.score} composite score)."
        )
        if historical_analogue and historical_analogue["sample_count"] >= 5:
            conclusion += (
                f" Similar {historical_analogue['event_type']} events historically closed higher "
                f"{historical_analogue['win_rate_pct']}% of the time over the next day "
                f"({historical_analogue['sample_count']} comparable events)."
            )
    else:
        conclusion = f"News found for {stock.symbol} but no composite signal has been scored yet."

    return {
        "symbol": stock.symbol,
        "signal": None if not latest_signal else {
            "direction": latest_signal.direction.value, "score": latest_signal.score,
            "confidence": latest_signal.confidence, "timestamp": latest_signal.timestamp.isoformat(),
        },
        "drivers": drivers,
        "recent_news": recent_news,
        "historical_analogue": historical_analogue,
        "conclusion": conclusion,
    }
