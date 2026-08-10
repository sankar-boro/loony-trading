"""Deterministic demo news provider — no API key required (spec §41 demo
mode). Every item is explicitly labeled [DEMO DATA] in its own content so
it can never be mistaken for a real market event downstream."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from .provider import RawNewsItem

_CANNED: list[dict] = [
    {
        "source": "Demo Wire",
        "title": "Reliance Industries beats Q1 profit estimates by 12%, stock surges",
        "content": ("Reliance Industries reported quarterly net profit ahead of "
                    "analyst estimates, driven by strong refining margins and "
                    "retail growth. [DEMO DATA]"),
        "minutes_ago": 5,
        "url": "https://example.com/demo/reliance-q1-beat",
    },
    {
        "source": "Demo Wire",
        "title": "HDFC Bank announces management change as CFO steps down",
        "content": ("HDFC Bank said its Chief Financial Officer will step down "
                    "next quarter, with the board initiating a search for a "
                    "successor. [DEMO DATA]"),
        "minutes_ago": 22,
        "url": "https://example.com/demo/hdfcbank-cfo-change",
    },
    {
        "source": "Demo Wire",
        "title": "TCS wins large multi-year IT services contract from European bank",
        "content": ("Tata Consultancy Services announced a new multi-year digital "
                    "transformation deal, its second major win this quarter. "
                    "[DEMO DATA]"),
        "minutes_ago": 47,
        "url": "https://example.com/demo/tcs-contract-win",
    },
    {
        "source": "Demo Wire",
        "title": "RBI keeps repo rate unchanged, cites inflation concerns",
        "content": ("The Reserve Bank of India held its policy rate steady, "
                    "flagging persistent food-price inflation. Banking stocks "
                    "were mixed in reaction. [DEMO DATA]"),
        "minutes_ago": 90,
        "url": "https://example.com/demo/rbi-rate-decision",
    },
    {
        "source": "Demo Wire",
        "title": "Adani Enterprises shares fall after brokerage downgrade",
        "content": ("A leading brokerage cut its rating on Adani Enterprises "
                    "citing valuation concerns following the recent rally. "
                    "[DEMO DATA]"),
        "minutes_ago": 130,
        "url": "https://example.com/demo/adanient-downgrade",
    },
]


class DemoNewsProvider:
    def get_latest_news(self, limit: int = 20) -> list[RawNewsItem]:
        now = datetime.now(timezone.utc)
        items = [
            RawNewsItem(
                source=c["source"], title=c["title"], url=c["url"],
                published_at=now - timedelta(minutes=c["minutes_ago"]),
                content=c["content"],
            )
            for c in _CANNED
        ]
        return items[:limit]
