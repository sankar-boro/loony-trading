#!/usr/bin/env python3
"""
Create the handbook tables in Postgres and load docs/ into them.

    python scripts/migrate_docs.py               # create tables (if missing), then load the docs
    python scripts/migrate_docs.py --tables-only # create tables only
    python scripts/migrate_docs.py --write-sql   # regenerate db/sql/handbook.sql from db/models.py

The tables are defined in db/sql/handbook.sql (CREATE TABLE / CREATE INDEX
only, IF NOT EXISTS, so it is safe to run again). It names no schema: the
script runs it with the search_path set to DB_SCHEMA (from .env), so the
tables land in that schema; by hand:

    PGOPTIONS=-csearch_path=basic psql -d loony_trading -f db/sql/handbook.sql

Loading is incremental: only chapters whose markdown changed are rewritten,
and chapters removed from docs/book.yaml are deleted. docs/ stays the source
of truth. The same tables are also created by `alembic upgrade head`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SQL_FILE = ROOT / "db" / "sql" / "handbook.sql"


def build_sql() -> str:
    """DDL for the handbook tables, compiled from the SQLAlchemy models."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable
    from db.models import DocChapter, DocSection

    dialect = postgresql.dialect()
    out = [
        "-- The Loony Trading Handbook: table definitions (no data).",
        "-- Generated from db/models.py by `python scripts/migrate_docs.py --write-sql`.",
        "-- Schema-neutral: the tables are created in the first schema of the",
        "-- search_path. scripts/migrate_docs.py sets it to DB_SCHEMA and then",
        "-- loads docs/ into the tables.",
        "",
    ]
    for model in (DocChapter, DocSection):
        table = model.__table__
        ddl = str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip()
        out.append("\n".join(line.rstrip() for line in ddl.splitlines()) + ";")
        for index in sorted(table.indexes, key=lambda i: i.name):
            out.append(str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect)) + ";")
        out.append("")
    return "\n".join(out)


def ensure_schema(conn, schema: str) -> None:
    """Create DB_SCHEMA if missing. A role that does not own the database
    cannot, so say what the owner has to run."""
    from sqlalchemy import text
    exists = conn.execute(text("SELECT 1 FROM pg_namespace WHERE nspname = :s"), {"s": schema}).scalar()
    if exists:
        return
    try:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.commit()
        print(f"Created schema {schema}")
    except Exception:
        conn.rollback()
        user = conn.engine.url.username
        db = conn.engine.url.database
        raise SystemExit(
            f"Schema {schema!r} does not exist and {user} may not create it. As the database "
            f"owner or a superuser run:\n"
            f'  sudo -u postgres psql -d {db} -c "CREATE SCHEMA {schema} AUTHORIZATION {user};"')


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the handbook tables and load docs/ into them")
    parser.add_argument("--tables-only", action="store_true", help="create the tables, do not load the docs")
    parser.add_argument("--write-sql", action="store_true",
                        help=f"regenerate {SQL_FILE.relative_to(ROOT)} from db/models.py and exit")
    args = parser.parse_args()

    if args.write_sql:
        SQL_FILE.parent.mkdir(parents=True, exist_ok=True)
        SQL_FILE.write_text(build_sql(), encoding="utf-8")
        print(f"Wrote {SQL_FILE.relative_to(ROOT)}")
        return 0

    from sqlalchemy import text
    from db.base import DB_SCHEMA, engine, session_scope

    where = engine.url.render_as_string(hide_password=True) + (f" (schema {DB_SCHEMA})" if DB_SCHEMA else "")
    print(f"Database: {where}")
    with engine.connect() as conn:
        if DB_SCHEMA:
            ensure_schema(conn, DB_SCHEMA)
        conn.exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))
        conn.commit()
        schema = conn.execute(text("SELECT current_schema()")).scalar()
    print(f"Tables ready: {schema}.doc_chapters, {schema}.doc_sections")

    if args.tables_only:
        return 0

    from db.docs_sync import sync_docs
    with session_scope() as db:
        report = sync_docs(db)
    print(f"Docs loaded: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
