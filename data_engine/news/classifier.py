"""
LLM-backed news event classification (MarketPulse AI Phase 1).

Reuses the Phase 0 LLM abstraction (ai.get_llm_provider) and the
StructuredAnalysis schema so every classification is Pydantic-validated —
never raw, untrusted LLM text (spec §50).
"""
from __future__ import annotations
from typing import Iterable

from ai import StructuredAnalysis, get_llm_provider
from ai.client import LLMProvider

# Spec §9 taxonomy, collapsed to stable machine-readable slugs.
NEWS_EVENT_TYPES = (
    "earnings", "revenue", "profit_warning", "guidance", "management_change",
    "ma", "acquisition", "partnership", "contract_win", "order_win",
    "regulatory_approval", "regulatory_action", "government_policy",
    "product_launch", "litigation", "debt", "credit_rating", "dividend",
    "buyback", "promoter_activity", "insider_activity", "fii_dii_activity",
    "brokerage_upgrade", "brokerage_downgrade", "sector_news", "macro_news",
    "commodity_shock", "currency_shock", "geopolitical_event", "other",
)

_SYSTEM_PROMPT = (
    "You are a financial news analyst for Indian equity markets (NSE/BSE). "
    "Classify the news article and produce a structured, evidence-based "
    "analysis. Do not predict future prices — describe what the news says "
    "and its likely relevance only.\n\n"
    f"event_type must be exactly one of: {', '.join(NEWS_EVENT_TYPES)}.\n\n"
    "confidence and impact_score are 0-1. catalyst_score is 0-10, judged on "
    "materiality, surprise, recency, and source credibility.\n\n"
    "affected_stocks must only include tickers you are confident are "
    "directly named or clearly implicated by the article — the candidate "
    "list below is a deterministic keyword match, not a guarantee; drop "
    "any candidate the article doesn't actually support, and you may add "
    "others the candidate list missed.\n\n"
    "If the article gives insufficient information to judge impact, keep "
    "confidence low and say why in evidence rather than guessing."
)


class NewsClassifier:
    def __init__(self, provider: LLMProvider | None = None):
        self._provider = provider or get_llm_provider()

    def classify(
        self, *, title: str, content: str, candidate_stocks: Iterable[str],
    ) -> StructuredAnalysis:
        prompt = (
            f"Headline: {title}\n\n"
            f"Body: {content[:4000]}\n\n"
            f"Candidate stocks (deterministic keyword match): "
            f"{', '.join(candidate_stocks) or 'none'}"
        )
        result = self._provider.complete_structured(
            system=_SYSTEM_PROMPT, prompt=prompt, schema=StructuredAnalysis,
        )
        normalized = _normalize_event_type(result.event_type)
        if normalized != result.event_type:
            result = result.model_copy(update={"event_type": normalized})
        return result


def _normalize_event_type(event_type: str) -> str:
    """Pydantic validates StructuredAnalysis' shape, but event_type is a
    free string — this is the belt-and-suspenders check that its *value*
    actually lands in the taxonomy, whether the drift comes from a real
    model near-miss ("Earnings" vs "earnings") or the demo provider's
    placeholder text."""
    slug = event_type.strip().lower().replace(" ", "_").replace("-", "_")
    return slug if slug in NEWS_EVENT_TYPES else "other"
