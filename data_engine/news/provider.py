"""News provider abstraction (MarketPulse AI Phase 1)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class RawNewsItem:
    source: str
    title: str
    url: str
    published_at: datetime
    content: str
    author: str | None = None
    language: str = "en"


class NewsProvider(Protocol):
    def get_latest_news(self, limit: int = 20) -> list[RawNewsItem]: ...
