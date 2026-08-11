"""
Structured LLM output schemas (MarketPulse AI Phase 0).

Every LLM call in this project must return one of these — never raw
text. Matches the JSON shape from the master prompt's "AI output schema"
section.
"""
from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, Field


class StructuredAnalysis(BaseModel):
    """General-purpose event/news analysis. Used by the Phase 1 news
    pipeline."""

    summary: str
    event_type: str
    direction: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0, le=1)
    catalyst_score: float = Field(ge=0, le=10)
    impact_score: float = Field(ge=0, le=1)
    time_horizon: str
    affected_stocks: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidating_conditions: list[str] = Field(default_factory=list)


class CopilotAnswer(BaseModel):
    """Phase 6 copilot's final response — composed only from data the
    retrieval layer actually found, never from the model's own
    knowledge. `insufficient_evidence` is the model's own signal that the
    retrieved data didn't support a real answer (spec §50)."""

    answer: str
    confidence: Literal["low", "medium", "high"]
    evidence: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
