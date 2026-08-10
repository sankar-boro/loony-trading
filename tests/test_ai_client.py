"""Tests for the Phase 0 LLM provider abstraction."""
from __future__ import annotations
import os

import pytest

from ai.client import DemoLLMProvider, get_llm_provider, AnthropicProvider
from ai.schemas import StructuredAnalysis


def test_demo_provider_returns_valid_schema_instance():
    provider = DemoLLMProvider()
    result = provider.complete_structured(
        system="You analyze NSE news.",
        prompt="RELIANCE beats earnings estimates by 12%, stock up 3%",
        schema=StructuredAnalysis,
    )
    assert isinstance(result, StructuredAnalysis)
    assert 0 <= result.confidence <= 1
    assert 0 <= result.catalyst_score <= 10
    assert result.direction in ("bullish", "bearish", "neutral")


def test_demo_provider_is_schema_agnostic():
    from pydantic import BaseModel, Field
    from typing import Literal

    class OtherSchema(BaseModel):
        label: Literal["a", "b"]
        weight: float = Field(ge=0, le=100)
        tags: list[str]

    result = DemoLLMProvider().complete_structured(system="", prompt="x", schema=OtherSchema)
    assert isinstance(result, OtherSchema)
    assert result.label == "a"
    assert result.weight == 50.0
    assert result.tags == []


def test_factory_defaults_to_demo_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert isinstance(get_llm_provider(), DemoLLMProvider)


def test_factory_uses_demo_by_default(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_llm_provider(), DemoLLMProvider)


def test_factory_uses_anthropic_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    assert isinstance(get_llm_provider(), AnthropicProvider)
