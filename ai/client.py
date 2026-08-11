"""
LLM provider abstraction (MarketPulse AI Phase 0).

Two providers:
  - AnthropicProvider — real calls via the Anthropic SDK, structured/validated
    output through `messages.parse(output_format=...)`.
  - DemoLLMProvider   — deterministic, schema-agnostic canned responses.
    No API key needed, so the app can run cold (spec §41 demo mode) before
    Phase 8 builds the rest of demo mode out.

`get_llm_provider()` picks one from env: LLM_PROVIDER=anthropic (+
ANTHROPIC_API_KEY) for the real thing, anything else (default) for demo.
"""
from __future__ import annotations
import os
import typing
from typing import Protocol, Type, TypeVar

from pydantic import BaseModel
from pydantic.fields import FieldInfo

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5"


class LLMProvider(Protocol):
    def complete_structured(self, *, system: str, prompt: str, schema: Type[T]) -> T: ...


class AnthropicProvider:
    def __init__(self, model: str | None = None):
        import anthropic
        self._client = anthropic.Anthropic()
        self._model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    def complete_structured(self, *, system: str, prompt: str, schema: Type[T]) -> T:
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        return response.parsed_output


def _demo_field_value(field_name: str, field: FieldInfo, prompt: str) -> object:
    annotation = field.annotation
    origin = typing.get_origin(annotation)

    if origin is typing.Literal:
        return typing.get_args(annotation)[0]
    if origin in (list, typing.List):
        return []
    if annotation is bool:
        return False
    if annotation is float or annotation is int:
        lo, hi = 0.0, 1.0
        for meta in getattr(field, "metadata", []):
            if hasattr(meta, "ge") and meta.ge is not None:
                lo = meta.ge
            if hasattr(meta, "le") and meta.le is not None:
                hi = meta.le
        mid = (lo + hi) / 2
        return int(mid) if annotation is int else mid
    if annotation is str:
        return f"[DEMO] {field_name} for: {prompt[:60]}"
    return None


class DemoLLMProvider:
    """Fills any Pydantic schema with placeholder values, validated the
    same way a real response would be. Field values are schema-agnostic —
    works for StructuredAnalysis today and whatever Phase 1+ schemas add."""

    def complete_structured(self, *, system: str, prompt: str, schema: Type[T]) -> T:
        values = {
            name: _demo_field_value(name, field, prompt)
            for name, field in schema.model_fields.items()
        }
        return schema(**values)


def get_llm_provider() -> LLMProvider:
    provider = os.environ.get("LLM_PROVIDER", "demo").lower()
    if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicProvider()
    return DemoLLMProvider()
