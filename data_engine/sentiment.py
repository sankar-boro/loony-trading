import asyncio
import re
from typing import Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("sentiment")


class SentimentScore:
    def __init__(self, asset: str, score: float, source: str, raw: str = ""):
        self.asset = asset
        self.score = score      # -1.0 to 1.0
        self.source = source
        self.raw = raw


class SentimentFetcher:
    """
    Aggregates sentiment from NewsAPI and Reddit (optional).
    Score: -1 (very bearish) to +1 (very bullish).
    """

    def __init__(self, cfg: dict):
        self.news_api_key = cfg.get("NEWS_API_KEY", "")
        self._scores: Dict[str, float] = {}

    async def fetch(self, assets: List[str]) -> Dict[str, float]:
        tasks = [self._fetch_news(a) for a in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for asset, result in zip(assets, results):
            if isinstance(result, float):
                self._scores[asset] = result
        return dict(self._scores)

    async def _fetch_news(self, asset: str) -> float:
        if not self.news_api_key:
            return 0.0
        try:
            import aiohttp
            query = asset.replace("/", " ").replace("USDT", "").strip()
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": query,
                "sortBy": "publishedAt",
                "pageSize": 20,
                "apiKey": self.news_api_key,
                "language": "en",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as r:
                    data = await r.json()
            articles = data.get("articles", [])
            if not articles:
                return 0.0
            scores = [self._vader_score(f"{a['title']} {a.get('description', '')}") for a in articles]
            return sum(scores) / len(scores)
        except Exception as e:
            logger.debug(f"News fetch failed for {asset}: {e}")
            return 0.0

    def _vader_score(self, text: str) -> float:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            sia = SentimentIntensityAnalyzer()
            return sia.polarity_scores(text)["compound"]
        except ImportError:
            return self._simple_score(text)

    _BULLISH = {"bull", "surge", "rally", "gain", "up", "rise", "buy", "moon", "breakout"}
    _BEARISH = {"bear", "crash", "drop", "fall", "sell", "down", "dump", "loss", "decline"}

    def _simple_score(self, text: str) -> float:
        words = set(re.findall(r"\b\w+\b", text.lower()))
        b = len(words & self._BULLISH)
        s = len(words & self._BEARISH)
        total = b + s
        return (b - s) / total if total else 0.0

    def get(self, asset: str) -> float:
        return self._scores.get(asset, 0.0)
