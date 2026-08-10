"""
Deterministic entity resolution: free text -> Stock symbols.

Uses ticker symbols and company-name aliases derived from
config/instruments.py — not the LLM (spec §10: "Do NOT rely solely on an
LLM" for entity resolution). The LLM classifier still gets a chance to add
stocks it recognizes from context (e.g. "the bank" after a preceding
sentence names it), but this module is the deterministic first pass.

Ticker symbols and company-name aliases are matched separately and
differently on purpose. Several NSE tickers are also common English words
(PERSISTENT, IDEA, RAIN) — matching them case-insensitively produces false
positives like "persistent food-price inflation" -> Persistent Systems.
Tickers are therefore matched case-sensitively against the raw text (real
articles write them in caps); company names, which are distinctive enough
not to collide with ordinary prose, are matched case-insensitively.
"""
from __future__ import annotations
import re

from config.instruments import STOCK_UNIVERSE

_STRIP_WORDS = {
    "ltd", "limited", "india", "industries", "the", "inc", "corporation",
    "corp", "company", "co", "and",
}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower())


def _name_aliases_for(info: dict) -> set[str]:
    aliases: set[str] = set()
    name = _normalize(info["name"]).strip()
    if name:
        aliases.add(name)
    words = [w for w in name.split() if w and w not in _STRIP_WORDS]
    if words:
        aliases.add(" ".join(words))
    return {a for a in aliases if len(a) >= 3}


def _build_name_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for symbol, info in STOCK_UNIVERSE.items():
        for alias in _name_aliases_for(info):
            # First stock to claim an alias keeps it — avoids ambiguous
            # short aliases silently flipping between symbols.
            index.setdefault(alias, symbol)
    return index


_NAME_ALIAS_INDEX = _build_name_alias_index()
_NAME_PATTERNS = [
    (re.compile(rf"\b{re.escape(alias)}\b"), symbol)
    for alias, symbol in _NAME_ALIAS_INDEX.items()
]
_SYMBOL_PATTERNS = [
    (re.compile(rf"\b{re.escape(symbol)}\b"), symbol)
    for symbol in STOCK_UNIVERSE
]


def resolve_stock_mentions(text: str) -> list[str]:
    """Return sorted, deduplicated stock symbols mentioned in `text`."""
    found = {symbol for pattern, symbol in _SYMBOL_PATTERNS if pattern.search(text)}
    normalized = _normalize(text)
    found |= {symbol for pattern, symbol in _NAME_PATTERNS if pattern.search(normalized)}
    return sorted(found)
