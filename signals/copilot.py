"""
AI Market Copilot (MarketPulse AI Phase 6).

Two-step design, deliberately not "ask the LLM to figure out the whole
thing": a small deterministic keyword router decides which *kind* of
question this is and pulls the matching data straight out of Postgres,
then the LLM's only job is turning that retrieved JSON into a readable
answer — never inventing facts, and saying "insufficient evidence" when
the data doesn't support one (spec §4: don't use an LLM for anything a
deterministic pass can do; spec §50: hallucination protection).

The keyword router is intentionally narrow — it is not real NLU. It
covers the question shapes from the master prompt's copilot examples
(why is X moving, unusual volume, bullish/bearish/watch signals, recent
news, historical analogues) and returns "unsupported" for anything else,
which short-circuits before any LLM call — there's nothing to ground an
answer in, so nothing is asked of the model.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ai import CopilotAnswer, get_llm_provider
from ai.client import LLMProvider
from data_engine.news.entity_resolution import resolve_stock_mentions
from db.models import NewsArticle, NewsEvent, Signal, SignalDirection, Stock, StockEvent
from signals.historical import find_analogues
from signals.queries import latest_signal_per_stock
from signals.why import explain_move

_UNUSUAL_VOLUME_THRESHOLD = 75.0
_DEFAULT_LIMIT = 10

_ANSWER_SYSTEM_PROMPT = (
    "You are a market-intelligence copilot for Indian equities (NSE/BSE). "
    "Answer the user's question using ONLY the retrieved data provided — "
    "never use outside knowledge, never invent prices, news, statistics, or "
    "company names not present in the data. If the retrieved data doesn't "
    "actually answer the question, set insufficient_evidence=true and say so "
    "plainly rather than guessing. List what you drew on in the evidence "
    "field. Use measured language ('setup', 'signal', 'historical analysis') "
    "— never guarantee future performance or predict prices."
)


@dataclass
class CopilotIntent:
    query_type: str
    symbol: str | None = None
    direction: str | None = None
    event_type: str | None = None


@dataclass
class CopilotResult:
    answer: str
    confidence: str
    evidence: list[str]
    insufficient_evidence: bool
    retrieved: dict = field(default_factory=dict)


def _parse_intent(question: str) -> CopilotIntent:
    q = question.lower()
    symbols = resolve_stock_mentions(question)
    symbol = symbols[0] if symbols else None

    if "why" in q and symbol:
        return CopilotIntent("why_moving", symbol=symbol)
    if "volume" in q and any(w in q for w in ("unusual", "spike", "high", "surge")):
        return CopilotIntent("unusual_volume")
    if "bullish" in q:
        return CopilotIntent("signals_filter", direction="bullish")
    if "bearish" in q:
        return CopilotIntent("signals_filter", direction="bearish")
    if "watch" in q and "signal" in q:
        return CopilotIntent("signals_filter", direction="watch")
    if any(w in q for w in ("histor", "similar event", "analog")):
        return CopilotIntent("historical_analogue", symbol=symbol)
    if any(w in q for w in ("news", "event", "happened", "moving today")):
        return CopilotIntent("news_recent")
    if symbol:
        return CopilotIntent("why_moving", symbol=symbol)
    return CopilotIntent("unsupported")


def _latest_signals(db: Session, direction: str | None = None) -> list[dict]:
    """Every stock's most recent Signal — see signals/queries.py for why
    this must be a SQL-level latest-per-stock query, not a Python dedup
    over a truncated recency window."""
    q = latest_signal_per_stock(db)
    if direction:
        try:
            q = q.filter(Signal.direction == SignalDirection(direction))
        except ValueError:
            return []
    return [
        {
            "symbol": symbol, "direction": signal.direction.value, "score": signal.score,
            "confidence": signal.confidence, "volume_score": signal.volume_score,
            "timestamp": signal.timestamp.isoformat(),
        }
        for signal, symbol in q.all()
    ]


def _retrieve(db: Session, intent: CopilotIntent) -> tuple[dict, list[str]]:
    if intent.query_type == "why_moving":
        explanation = explain_move(db, intent.symbol) if intent.symbol else None
        if not explanation:
            return {}, []
        evidence = [f"Signal + news + historical analysis for {explanation['symbol']}"]
        evidence += [f"News: {n['headline']} ({n['source']}, {n['url']})" for n in explanation["recent_news"]]
        return {"why": explanation}, evidence

    if intent.query_type == "unusual_volume":
        signals = [s for s in _latest_signals(db) if (s["volume_score"] or 0) >= _UNUSUAL_VOLUME_THRESHOLD]
        signals.sort(key=lambda s: s["volume_score"], reverse=True)
        signals = signals[:_DEFAULT_LIMIT]
        if not signals:
            return {}, []
        evidence = [f"Signal for {s['symbol']}: volume_score={s['volume_score']}" for s in signals]
        return {"unusual_volume_signals": signals}, evidence

    if intent.query_type == "signals_filter":
        signals = _latest_signals(db, direction=intent.direction)
        signals.sort(key=lambda s: s["score"], reverse=True)
        signals = signals[:_DEFAULT_LIMIT]
        if not signals:
            return {}, []
        evidence = [f"Signal for {s['symbol']}: {s['direction']}, score={s['score']}" for s in signals]
        return {"signals": signals}, evidence

    if intent.query_type == "news_recent":
        rows = (
            db.query(NewsEvent, NewsArticle)
            .join(NewsArticle, NewsEvent.article_id == NewsArticle.id)
            .order_by(desc(NewsArticle.published_at))
            .limit(_DEFAULT_LIMIT)
            .all()
        )
        if not rows:
            return {}, []
        items = [
            {
                "headline": article.title, "source": article.source, "url": article.url,
                "published_at": article.published_at.isoformat(), "event_type": event.event_type,
                "impact_score": event.impact_score,
            }
            for event, article in rows
        ]
        evidence = [f"News: {i['headline']} ({i['source']}, {i['url']})" for i in items]
        return {"recent_news": items}, evidence

    if intent.query_type == "historical_analogue":
        event_type = intent.event_type
        direction = None
        if not event_type and intent.symbol:
            stock = db.query(Stock).filter(Stock.symbol == intent.symbol).first()
            if stock:
                latest = (
                    db.query(StockEvent, NewsEvent)
                    .join(NewsEvent, StockEvent.event_id == NewsEvent.id)
                    .filter(StockEvent.stock_id == stock.id)
                    .order_by(desc(StockEvent.created_at))
                    .first()
                )
                if latest:
                    event_type = latest[1].event_type
                    direction = latest[0].direction
        if not event_type:
            return {}, []
        result = find_analogues(db, event_type=event_type, direction=direction)
        if result.total_samples == 0:
            return {}, []
        horizons = [
            {"horizon": h.horizon, "sample_count": h.sample_count,
             "win_rate_pct": h.win_rate_pct, "median_return_pct": h.median_return_pct}
            for h in result.horizons
        ]
        evidence = [f"{result.total_samples} historical '{event_type}' events analyzed"]
        return {"historical_analogue": {"event_type": event_type, "horizons": horizons}}, evidence

    return {}, []


_UNSUPPORTED_ANSWER = (
    "I can currently answer questions about: why a stock is moving, "
    "bullish/bearish/watch signals, unusual trading volume, recent news, "
    "and historical analogues for a past event type. I don't have a way "
    "to answer that yet."
)


def answer_query(db: Session, question: str, provider: LLMProvider | None = None) -> CopilotResult:
    intent = _parse_intent(question)

    if intent.query_type == "unsupported":
        return CopilotResult(
            answer=_UNSUPPORTED_ANSWER, confidence="high",
            evidence=[], insufficient_evidence=True,
        )

    data, evidence = _retrieve(db, intent)
    if not data:
        return CopilotResult(
            answer="No matching data found in the database for this question.",
            confidence="high", evidence=[], insufficient_evidence=True,
        )

    provider = provider or get_llm_provider()
    prompt = (
        f"Question: {question}\n\n"
        f"Retrieved data (JSON — the ONLY facts you may use):\n{json.dumps(data, default=str)}"
    )
    result = provider.complete_structured(system=_ANSWER_SYSTEM_PROMPT, prompt=prompt, schema=CopilotAnswer)
    return CopilotResult(
        answer=result.answer, confidence=result.confidence,
        evidence=result.evidence or evidence,
        insufficient_evidence=result.insufficient_evidence,
        retrieved=data,
    )
