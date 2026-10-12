"""Loading the handbook into doc_chapters / doc_sections (db/docs_sync.py)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dashboard.backend.routers import doc_files
from db.base import Base
from db.docs_sync import split_sections, sync_docs
from db.models import DocChapter, DocSection


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def docs(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("# Alpha\n\nIntro.\n\n## First `one`\n\nx\n\n```\n## not a heading\n```\n\n## Second\n\ny\n")
    (tmp_path / "b.md").write_text("# Beta\n\nOnly intro.\n")
    (tmp_path / "book.yaml").write_text("title: T\nparts:\n  - title: P1\n    chapters: [a.md]\n"
                                        "  - title: P2\n    chapters: [b.md]\n")
    monkeypatch.setattr(doc_files, "_DOCS_DIR", tmp_path)
    monkeypatch.setattr(doc_files, "_MANIFEST", tmp_path / "book.yaml")
    return tmp_path


def test_split_sections_ignores_code_and_matches_anchors():
    secs = split_sections("# T\n\nintro\n\n## A b\n\n```\n## no\n```\n## A b\n")
    assert [(s["position"], s["anchor"], s["title"]) for s in secs] == \
        [(0, "", ""), (1, "a-b", "A b"), (2, "a-b-1", "A b")]
    assert secs[0]["content"].startswith("# T") and "## no" in secs[1]["content"]


def test_sync_inserts_then_is_idempotent(db, docs):
    r = sync_docs(db, docs)
    assert (r.added, r.updated, r.unchanged, r.removed) == (2, 0, 0, 0)
    a = db.scalar(select(DocChapter).where(DocChapter.path == "a.md"))
    assert (a.title, a.part, a.part_number, a.number) == ("Alpha", "P1", 1, 1)
    assert [s.title for s in a.sections] == ["", "First one", "Second"]
    assert [s.anchor for s in a.sections] == ["", "first-one", "second"]

    r = sync_docs(db, docs)
    assert (r.added, r.updated, r.unchanged, r.sections) == (0, 0, 2, 0)


def test_sync_updates_changed_and_removes_dropped(db, docs):
    sync_docs(db, docs)
    (docs / "a.md").write_text("# Alpha 2\n\n## Only\n")
    (docs / "book.yaml").write_text("parts:\n  - title: P1\n    chapters: [a.md]\n")
    (docs / "b.md").unlink()
    r = sync_docs(db, docs)
    db.commit()
    assert (r.updated, r.removed) == (1, 1)
    assert db.scalar(select(func.count()).select_from(DocChapter)) == 1
    assert db.scalar(select(func.count()).select_from(DocSection)) == 2
    assert db.scalar(select(DocChapter.title)) == "Alpha 2"


def test_real_handbook_loads(db):
    r = sync_docs(db)
    assert r.added == len([c for p in doc_files.load_book()["parts"] for c in p["chapters"]])
    assert db.scalar(select(DocChapter).where(DocChapter.path == "engine/intraday-controls.md")).sections


def test_handbook_sql_matches_the_models():
    """db/sql/handbook.sql is generated from db/models.py; regenerate it with
    `python scripts/migrate_docs.py --write-sql` after changing the models."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("migrate_docs", root / "scripts" / "migrate_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sql = (root / "db" / "sql" / "handbook.sql").read_text()
    assert sql == mod.build_sql()
    assert "INSERT" not in sql and "basic." not in sql
