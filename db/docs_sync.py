"""
Copy the handbook (docs/book.yaml + docs/**/*.md) into the doc_chapters and
doc_sections tables. The markdown files stay the source of truth; this
makes the same content queryable with SQL.

Idempotent: a chapter whose markdown is unchanged (same SHA-256) is left
alone, a changed one has its row and sections rewritten, and chapters no
longer in the book are deleted. Chapter numbers and part titles are always
refreshed, since inserting a chapter renumbers the ones after it.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from dashboard.backend.routers.doc_files import _DOCS_DIR, load_book, slugify
from db.models import DocChapter, DocSection

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")


@dataclass
class SyncReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    sections: int = 0

    def __str__(self) -> str:
        return (f"{self.added} added, {self.updated} updated, {self.unchanged} unchanged, "
                f"{self.removed} removed; {self.sections} sections written")


def split_sections(markdown: str) -> list[dict]:
    """[{position, anchor, title, content}] — position 0 is the text before
    the first `## ` heading. Headings inside code blocks are ignored, and
    anchors match the ids the dashboard generates for heading links."""
    seen: dict[str, int] = {}
    sections = [{"position": 0, "anchor": "", "title": "", "lines": []}]
    in_code = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else _HEADING.match(line)
        if m:
            anchor = slugify(m.group(2), seen)
            if len(m.group(1)) == 2:
                sections.append({"position": len(sections), "anchor": anchor,
                                 "title": re.sub(r"`|\*\*", "", m.group(2)), "lines": []})
        sections[-1]["lines"].append(line)
    return [{"position": s["position"], "anchor": s["anchor"], "title": s["title"],
             "content": "\n".join(s["lines"]).strip("\n") + "\n"} for s in sections]


def sync_docs(db: Session, docs_dir: Path = _DOCS_DIR) -> SyncReport:
    report = SyncReport()
    book = load_book()
    existing = {c.path: c for c in db.scalars(select(DocChapter))}
    now = datetime.now(timezone.utc)
    seen_paths = set()

    for part_number, part in enumerate(book["parts"], start=1):
        for ch in part["chapters"]:
            path = ch["path"]
            seen_paths.add(path)
            content = (docs_dir / path).read_text(encoding="utf-8")
            digest = hashlib.sha256(content.encode()).hexdigest()
            row = existing.get(path)
            if row is None:
                row = DocChapter(path=path)
                db.add(row)
                report.added += 1
            elif row.content_sha256 == digest:
                report.unchanged += 1
            else:
                report.updated += 1
            row.part, row.part_number = part["title"], part_number
            row.number, row.title = ch["number"], ch["title"]
            if row.content_sha256 != digest:
                row.content, row.content_sha256, row.updated_at = content, digest, now
                row.sections.clear()
                db.flush()        # delete old sections before re-inserting positions
                for s in split_sections(content):
                    row.sections.append(DocSection(**s))
                    report.sections += 1

    for path, row in existing.items():
        if path not in seen_paths:
            db.delete(row)
            report.removed += 1
    db.flush()
    return report
