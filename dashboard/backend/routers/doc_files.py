"""Serve the markdown files under ./docs/ so the dashboard can render them.

Mounted at /api/doc-files (not /api/docs — that path is FastAPI's Swagger UI).
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from ..config import ROOT

router = APIRouter()

_DOCS_DIR = (ROOT / "docs").resolve()


def _title(path) -> str:
    """First markdown H1 in the file, falling back to the file name."""
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return path.stem.replace("_", " ").replace("-", " ").title()


@router.get("/doc-files")
def list_doc_files() -> list[dict]:
    if not _DOCS_DIR.is_dir():
        return []
    files = sorted(
        _DOCS_DIR.rglob("*.md"),
        key=lambda p: (len(p.relative_to(_DOCS_DIR).parts), str(p).lower()),
    )
    return [
        {"path": p.relative_to(_DOCS_DIR).as_posix(), "title": _title(p)}
        for p in files
    ]


@router.get("/doc-files/{path:path}", response_class=PlainTextResponse)
def read_doc_file(path: str) -> str:
    target = (_DOCS_DIR / path).resolve()
    # Refuse anything outside docs/ (e.g. ../../.env) and non-markdown files.
    if not target.is_relative_to(_DOCS_DIR) or target.suffix != ".md" or not target.is_file():
        raise HTTPException(404, "Doc not found")
    return target.read_text(encoding="utf-8")
