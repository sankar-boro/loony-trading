"""
"Why is this stock moving?" explanation builder (MarketPulse AI Phase 4).

Fuses the latest persisted composite score, recent news, and historical
analogues into one evidence-backed explanation — every claim traces to a
DB row; if there's nothing to point at, this says so rather than
guessing (spec §27). Factored out of the /why route so the copilot
(Phase 6) can call the exact same logic instead of re-deriving it or
hitting its own API over HTTP.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.models import NewsArticle, NewsEvent, Signal, Stock, StockEvent
from signals.historical import find_analogues

_NEWS_LOOKBACK = timedelta(days=7)
_COMPONENT_LABEL = {
    "catalyst": "News catalyst", "technical": "Technical setup", "momentum": "Price momentum",
    "volume": "Volume activity", "historical": "Historical analogue", "regime": "Market regime",
    "risk": "Volatility/risk profile",
}
_WEIGHTS = {
    "catalyst": 0.25, "technical": 0.20, "momentum": 0.15, "volume": 0.15,
    "historical": 0.10, "regime": 0.10, "risk": 0.05,
}


def explain_move(db: Session, symbol: str) -> dict | None:
    """Returns None if the symbol is unknown; callers decide how to
    surface that (404 in the API, "unsupported" in the copilot)."""
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    if not stock:
        return None

    latest_signal = (
        db.query(Signal)
        .filter(Signal.stock_id == stock.id)
        .order_by(desc(Signal.timestamp))
        .first()
    )

    since = datetime.now(timezone.utc) - _NEWS_LOOKBACK
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
