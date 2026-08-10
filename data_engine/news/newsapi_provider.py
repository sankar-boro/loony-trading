"""Real news provider — NewsAPI.org `/v2/everything`, scoped to Indian
markets. Free tier: 100 requests/day, article availability delayed."""
from __future__ import annotations
import os
from datetime import datetime, timezone

import requests

from utils.logger import get_logger
from .provider import RawNewsItem

logger = get_logger("news.newsapi")

_URL = "https://newsapi.org/v2/everything"
_QUERY = "(NSE OR BSE OR Nifty OR Sensex OR \"Indian stocks\")"


class NewsAPIProvider:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("NEWS_API_KEY", "")

    def get_latest_news(self, limit: int = 20) -> list[RawNewsItem]:
        if not self.api_key:
            logger.warning("NEWS_API_KEY not set — returning no articles")
            return []

        params = {
            "q": _QUERY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": min(limit, 100),
            "apiKey": self.api_key,
        }
        try:
            resp = requests.get(_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"NewsAPI fetch failed: {e}")
            return []

        items: list[RawNewsItem] = []
        for a in data.get("articles", []):
            raw_ts = a.get("publishedAt", "")
            try:
                published = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                published = datetime.now(timezone.utc)
            items.append(RawNewsItem(
                source=(a.get("source") or {}).get("name", "unknown"),
                title=a.get("title") or "",
                url=a.get("url") or "",
                published_at=published,
                content=a.get("content") or a.get("description") or "",
                author=a.get("author"),
            ))
        return items
