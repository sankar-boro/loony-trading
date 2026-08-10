"""
News ingestion pipeline (MarketPulse AI Phase 1):

    fetch -> dedupe -> entity resolution -> LLM classification -> persist

Persists NewsArticle, NewsEvent, and one StockEvent per resolved stock.
"""
from __future__ import annotations
import hashlib
import os

from sqlalchemy.orm import Session

from db.models import NewsArticle, NewsEvent, StockEvent, Stock
from utils.logger import get_logger
from .classifier import NewsClassifier
from .demo_provider import DemoNewsProvider
from .entity_resolution import resolve_stock_mentions
from .newsapi_provider import NewsAPIProvider
from .provider import NewsProvider, RawNewsItem

logger = get_logger("news.pipeline")

_DIRECTION_TO_SENTIMENT = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}


def _is_configured(key: str) -> bool:
    """Filters out unfilled .env.example placeholders like
    'your_newsapi_key_here' — this repo's convention throughout — so a
    fresh checkout falls back to demo data instead of silently failing
    every request against a fake key."""
    return bool(key) and not (key.startswith("your_") or key.endswith("_here"))


def get_news_provider() -> NewsProvider:
    if _is_configured(os.environ.get("NEWS_API_KEY", "")):
        return NewsAPIProvider()
    return DemoNewsProvider()


def _hash_item(item: RawNewsItem) -> str:
    key = f"{item.source}|{item.title}|{item.url}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class NewsIngestionPipeline:
    def __init__(
        self,
        provider: NewsProvider | None = None,
        classifier: NewsClassifier | None = None,
    ):
        self.provider = provider or get_news_provider()
        self.classifier = classifier or NewsClassifier()

    def run_once(self, db: Session, limit: int = 20) -> dict:
        items = self.provider.get_latest_news(limit=limit)
        ingested = skipped_duplicate = events_created = 0

        for item in items:
            item_hash = _hash_item(item)
            if db.query(NewsArticle).filter(NewsArticle.hash == item_hash).first():
                skipped_duplicate += 1
                continue

            article = NewsArticle(
                source=item.source, title=item.title, url=item.url,
                published_at=item.published_at, content=item.content,
                author=item.author, language=item.language, hash=item_hash,
            )
            db.add(article)
            db.flush()
            ingested += 1

            candidates = resolve_stock_mentions(f"{item.title} {item.content}")
            analysis = self.classifier.classify(
                title=item.title, content=item.content, candidate_stocks=candidates,
            )

            event = NewsEvent(
                article_id=article.id,
                event_type=analysis.event_type,
                impact_score=analysis.impact_score,
                sentiment_score=_DIRECTION_TO_SENTIMENT[analysis.direction] * analysis.confidence,
                confidence=analysis.confidence,
                summary=analysis.summary,
            )
            db.add(event)
            db.flush()
            events_created += 1

            resolved_symbols = set(candidates) | {s.upper() for s in analysis.affected_stocks}
            for symbol in resolved_symbols:
                stock = db.query(Stock).filter(Stock.symbol == symbol).first()
                if not stock:
                    continue
                db.add(StockEvent(
                    stock_id=stock.id, event_id=event.id,
                    relevance_score=1.0 if symbol in candidates else 0.6,
                    direction=analysis.direction,
                ))

        db.commit()
        summary = {
            "fetched": len(items), "ingested": ingested,
            "skipped_duplicate": skipped_duplicate, "events_created": events_created,
        }
        logger.info(f"News ingestion: {summary}")
        return summary
