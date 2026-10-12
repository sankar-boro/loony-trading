"""The handbook under docs/ is served by the dashboard's Docs page. Keep it
navigable: every chapter in docs/book.yaml exists, every relative link and
section anchor resolves, and every markdown table has a consistent number of
cells (a stray "|" inside a cell silently breaks a table)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from dashboard.backend.routers.doc_files import load_book, slugify

DOCS = Path(__file__).resolve().parent.parent / "docs"
BOOK = yaml.safe_load((DOCS / "book.yaml").read_text())
CHAPTERS = [c for part in BOOK["parts"] for c in part["chapters"]]
ALL_MD = sorted(p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md"))


def _heading_ids(path: Path) -> set[str]:
    ids, seen, in_code = set(), {}, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        m = None if in_code else re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
        if m:
            ids.add(slugify(m.group(2), seen))
    return ids


def _without_code(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def test_every_manifest_chapter_exists():
    missing = [c for c in CHAPTERS if not (DOCS / c).is_file()]
    assert missing == []


def test_every_markdown_file_is_in_the_book():
    assert [p for p in ALL_MD if p not in CHAPTERS] == []


def test_book_api_numbers_chapters_in_order():
    book = load_book()
    numbers = [c["number"] for part in book["parts"] for c in part["chapters"]]
    assert numbers == list(range(1, len(CHAPTERS) + 1))


@pytest.mark.parametrize("chapter", ALL_MD)
def test_links_and_anchors_resolve(chapter):
    path = DOCS / chapter
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", _without_code(path.read_text(encoding="utf-8"))):
        if re.match(r"^[a-z]+:", target):
            continue                                   # external link
        file_part, _, anchor = target.partition("#")
        dest = (path.parent / file_part).resolve() if file_part else path
        if not dest.is_file():
            broken.append(target)
        elif anchor and anchor not in _heading_ids(dest):
            broken.append(target)
    assert broken == [], f"{chapter}: {broken}"


@pytest.mark.parametrize("chapter", ALL_MD)
def test_tables_are_well_formed(chapter):
    bad, cols, in_code = [], None, False
    for n, line in enumerate((DOCS / chapter).read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line.startswith("|"):
            cols = None
            continue
        cells = len(re.split(r"(?<!\\)\|", line.strip().strip("|")))
        if cols is None:
            cols = cells
        elif cells != cols:
            bad.append(n)
    assert bad == [], f"{chapter}: rows {bad} have the wrong number of cells"
