"""Hardcoded ISINs go stale when a company splits, issues bonus shares or
is renamed (10 had, in October 2026 — KOTAKBANK, BAJFINANCE, HAL, ...),
and Upstox then silently returns no data for that stock."""
from __future__ import annotations
import ast
import csv
import re
from pathlib import Path

import pytest

from config.instruments import INSTRUMENTS

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "data" / "instruments" / "NSE.csv"


def test_registry_isins_exist_in_upstox_master():
    if not MASTER.exists():
        pytest.skip("data/instruments/NSE.csv not downloaded (scripts/fetch_instruments.sh)")
    keys = {row[0] for row in csv.reader(MASTER.open()) if row and row[0].startswith("NSE_EQ|")}
    stale = sorted(sym for sym, key in INSTRUMENTS.items() if key.startswith("NSE_EQ|") and key not in keys)
    assert stale == [], f"ISINs not in the Upstox instrument master: {stale}"


# An ISIN, or an exchange-qualified instrument key such as "NSE_INDEX|Nifty 50"
_KEY_LITERAL = re.compile(r"\bIN[EF][0-9A-Z]{9}\b|\b(?:NSE|BSE)_(?:EQ|INDEX)\|[A-Za-z]")
_SOURCE_OF_TRUTH = ROOT / "config" / "instruments.py"
_SKIP_DIRS = {"tests", "node_modules", ".venv", "venv", "alembic", "__pycache__"}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def test_instrument_keys_only_live_in_config_instruments():
    """Every stock ISIN and index key comes from config/instruments.py; code
    looks them up (INSTRUMENTS["TCS"], INDEX_INSTRUMENTS["NIFTY50"]) instead
    of keeping its own copy that can go stale. Docstrings and comments may
    show example keys."""
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if path == _SOURCE_OF_TRUTH or _SKIP_DIRS & set(rel.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings and _KEY_LITERAL.search(node.value)):
                offenders.append(f"{rel}:{node.lineno}: {node.value[:50]!r}")
    assert offenders == [], "Hardcoded instrument keys (use config/instruments.py):\n" + "\n".join(offenders)
