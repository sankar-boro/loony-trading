"""
Database engine, session factory, and declarative base.

The connection comes from the environment (the project's .env is loaded
first), in this order:

  1. DATABASE_URL — a full SQLAlchemy URL
  2. DB_NAME, DB_HOST, DB_PORT (5432), DB_USERNAME, DB_PASSWORD
  3. the docker-compose `db` service's local-dev equivalent (localhost:5432),
     so `alembic upgrade head` and the test suite work identically whether
     Postgres is reached via compose or run locally

DB_SCHEMA (optional) puts every table in that Postgres schema instead of
`public`: it becomes the connection's search_path, and Alembic creates it
and keeps its version table there.
"""
from __future__ import annotations
import os
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.loader import load_dotenv

load_dotenv()


def _database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if os.environ.get("DB_NAME"):
        user = quote_plus(os.environ.get("DB_USERNAME", ""))
        password = quote_plus(os.environ.get("DB_PASSWORD", ""))
        auth = f"{user}:{password}@" if password else (f"{user}@" if user else "")
        host = os.environ.get("DB_HOST", "localhost")
        port = os.environ.get("DB_PORT", "5432")
        return f"postgresql+psycopg2://{auth}{host}:{port}/{os.environ['DB_NAME']}"
    return "postgresql+psycopg2://loony:loony@localhost:5432/loony_trading"


DATABASE_URL = _database_url()
DB_SCHEMA = os.environ.get("DB_SCHEMA", "").strip() or None

_connect_args = (
    {"options": f"-csearch_path={DB_SCHEMA}"}
    if DB_SCHEMA and DATABASE_URL.startswith("postgresql") else {}
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: `db: Session = Depends(get_db)`."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """For scripts/workers outside FastAPI's request lifecycle."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
