from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.base import get_db
from db.models import NewsArticle, NewsEvent, Stock, StockEvent
from data_engine.news.classifier import NEWS_EVENT_TYPES
from data_engine.news.pipeline import NewsIngestionPipeline

router = APIRouter()


@router.get("/news")
def list_news(
    event_type: str | None = None,
    symbol: str | None = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = (
        db.query(NewsEvent, NewsArticle)
        .join(NewsArticle, NewsEvent.article_id == NewsArticle.id)
        .order_by(desc(NewsArticle.published_at))
    )
    if event_type:
        q = q.filter(NewsEvent.event_type == event_type)
    if symbol:
        q = (
            q.join(StockEvent, StockEvent.event_id == NewsEvent.id)
            .join(Stock, Stock.id == StockEvent.stock_id)
            .filter(Stock.symbol == symbol.upper())
        )

    rows = q.limit(limit).all()
    out = []
    for event, article in rows:
        stocks = (
            db.query(Stock.symbol)
            .join(StockEvent, StockEvent.stock_id == Stock.id)
            .filter(StockEvent.event_id == event.id)
            .all()
        )
        out.append({
            "id": event.id,
            "headline": article.title,
            "source": article.source,
            "url": article.url,
            "published_at": article.published_at.isoformat(),
            "event_type": event.event_type,
            "sentiment_score": event.sentiment_score,
            "impact_score": event.impact_score,
            "confidence": event.confidence,
            "summary": event.summary,
            "affected_stocks": [s[0] for s in stocks],
        })
    return out


@router.get("/news/event-types")
def list_event_types() -> list[str]:
    return list(NEWS_EVENT_TYPES)


@router.post("/news/ingest")
def trigger_ingest(limit: int = 20, db: Session = Depends(get_db)) -> dict:
    """Manual ingestion trigger — a declarative scheduler replaces this
    call site in Phase 11; for now this is also how the demo/local dev
    loop refreshes the News Terminal."""
    pipeline = NewsIngestionPipeline()
    return pipeline.run_once(db, limit=limit)
