"""Serve the handbook under ./docs/ so the dashboard can render it as a book.

docs/book.yaml lists the parts and, in reading order, the chapter files in
each part. A chapter's title is its first `# ` heading; its sections are its
`## ` headings. Mounted at /api/doc-files (not /api/docs — that path is
FastAPI's Swagger UI).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ..config import ROOT

router = APIRouter()

_DOCS_DIR = (ROOT / "docs").resolve()
_MANIFEST = _DOCS_DIR / "book.yaml"


def slugify(text: str, seen: dict[str, int]) -> str:
    """Heading id, matching what rehype-slug (github-slugger) generates in the
    browser, so section links from the table of contents land on the heading."""
    text = re.sub(r"`|\*\*|__|\[([^\]]*)\]\([^)]*\)", r"\1", text)   # strip inline markdown
    slug = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    n = seen.get(slug, 0)
    seen[slug] = n + 1
    return slug if n == 0 else f"{slug}-{n}"


def _parse_chapter(path: Path) -> tuple[str, list[dict]]:
    """(title, sections) — sections are the `## ` headings outside code blocks."""
    title = path.stem.replace("_", " ").replace("-", " ").title()
    sections: list[dict] = []
    seen: dict[str, int] = {}
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
        if not m:
            continue
        level, text = len(m.group(1)), m.group(2)
        slug = slugify(text, seen)
        if level == 1 and not sections:
            title = re.sub(r"`", "", text)
        elif level == 2:
            sections.append({"id": slug, "title": re.sub(r"`|\*\*", "", text)})
    return title, sections


def _resolve(rel: str) -> Path:
    target = (_DOCS_DIR / rel).resolve()
    # Refuse anything outside docs/ (e.g. ../../.env) and non-markdown files.
    if not target.is_relative_to(_DOCS_DIR) or target.suffix != ".md" or not target.is_file():
        raise HTTPException(404, "Doc not found")
    return target


def load_book() -> dict:
    """The book: parts → chapters (numbered across the whole book) → sections.
    Markdown files under docs/ that the manifest does not list are appended
    as a final "Other documents" part, so nothing is ever unreachable."""
    manifest = yaml.safe_load(_MANIFEST.read_text()) if _MANIFEST.exists() else {}
    parts, listed, number = [], set(), 0
    for part in manifest.get("parts", []):
        chapters = []
        for rel in part.get("chapters", []):
            path = _DOCS_DIR / rel
            if not path.is_file():
                continue
            number += 1
            title, sections = _parse_chapter(path)
            chapters.append({"path": rel, "title": title, "number": number, "sections": sections})
            listed.add(rel)
        if chapters:
            parts.append({"title": part.get("title", ""), "chapters": chapters})

    extra = sorted(p.relative_to(_DOCS_DIR).as_posix() for p in _DOCS_DIR.rglob("*.md")) if _DOCS_DIR.is_dir() else []
    extra = [rel for rel in extra if rel not in listed]
    if extra:
        chapters = []
        for rel in extra:
            number += 1
            title, sections = _parse_chapter(_DOCS_DIR / rel)
            chapters.append({"path": rel, "title": title, "number": number, "sections": sections})
        parts.append({"title": "Other documents", "chapters": chapters})

    return {"title": manifest.get("title", "Documentation"),
            "subtitle": manifest.get("subtitle", ""),
            "parts": parts}


@router.get("/doc-files")
def get_book() -> dict:
    return load_book()


@router.get("/doc-files/search")
def search_docs(q: str = Query(..., min_length=2), limit: int = Query(40, le=100)) -> list[dict]:
    """Case-insensitive full-text search. One hit per matching line, tagged
    with the chapter and the section it falls under."""
    needle = q.lower()
    hits: list[dict] = []
    for part in load_book()["parts"]:
        for ch in part["chapters"]:
            seen: dict[str, int] = {}
            section = {"id": "", "title": ""}
            in_code = False
            for line in (_DOCS_DIR / ch["path"]).read_text(encoding="utf-8").splitlines():
                if line.startswith("```"):
                    in_code = not in_code
                heading = None if in_code else re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
                if heading:
                    slug = slugify(heading.group(2), seen)
                    if len(heading.group(1)) == 2:
                        section = {"id": slug, "title": re.sub(r"`|\*\*", "", heading.group(2))}
                if needle in line.lower():
                    text = re.sub(r"[`*_#>|]", "", line).strip()
                    i = text.lower().find(needle)
                    start = max(0, i - 60)
                    hits.append({
                        "path": ch["path"], "chapter": ch["title"], "number": ch["number"],
                        "section_id": slug if heading else section["id"],
                        "section": section["title"],
                        "snippet": ("…" if start else "") + text[start:i + len(needle) + 80],
                    })
                    if len(hits) >= limit:
                        return hits
    return hits


@router.get("/doc-files/{path:path}", response_class=PlainTextResponse)
def read_doc_file(path: str) -> str:
    return _resolve(path).read_text(encoding="utf-8")
