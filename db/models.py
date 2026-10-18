"""
ORM models for the MarketPulse AI persistence layer (Phase 0).

Column types stick to portable SQLAlchemy generics (String, JSON, DateTime)
rather than Postgres-only constructs (JSONB, native ENUM) so the same
models work against SQLite in tests and Postgres in docker-compose without
a second code path.
"""
from __future__ import annotations
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, DateTime, Enum, Float, ForeignKey, Index, Integer, String,
    UniqueConstraint, Boolean, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Reference data ──────────────────────────────────────────────────────────

class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE_EQ")
    company_name: Mapped[str] = mapped_column(String(128))
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    market_cap: Mapped[str | None] = mapped_column(String(16), nullable=True)  # Large/Mid/Small Cap
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ── Market data ──────────────────────────────────────────────────────────────

class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("stock_id", "timestamp", "timeframe", name="uq_pricebar_stock_ts_tf"),
        Index("ix_pricebar_stock_ts", "stock_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)  # "1m","15m","1d",...
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)

    stock: Mapped["Stock"] = relationship()


# ── News / events ────────────────────────────────────────────────────────────

class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (Index("ix_news_published_at", "published_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # dedup key
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class NewsEvent(Base):
    __tablename__ = "news_events"
    __table_args__ = (Index("ix_newsevent_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32))       # earnings, guidance, ma, ...
    event_subtype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    impact_score: Mapped[float] = mapped_column(Float)        # 0-1
    catalyst_score: Mapped[float] = mapped_column(Float, default=0)  # 0-10 — materiality/surprise/recency/credibility
    sentiment_score: Mapped[float] = mapped_column(Float)     # -1..1
    confidence: Mapped[float] = mapped_column(Float)          # 0-1
    summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    article: Mapped["NewsArticle"] = relationship()


class StockEvent(Base):
    __tablename__ = "stock_events"
    __table_args__ = (Index("ix_stockevent_stock_created", "stock_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("news_events.id"), nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float)     # 0-1, how directly this event concerns the stock
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)  # bullish/bearish/neutral
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    stock: Mapped["Stock"] = relationship()
    event: Mapped["NewsEvent"] = relationship()


# ── Signals & trade setups ───────────────────────────────────────────────────

class SignalDirection(str, enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    WATCH = "watch"
    NO_SIGNAL = "no_signal"


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signal_stock_ts", "stock_id", "timestamp"),
        Index("ix_signal_score", "score"),
        Index("ix_signal_stock_tf_ts", "stock_id", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    # Bar size this signal was scored from ("1d", "15m", "5m", ...) —
    # intraday-gap fix Phase 5 (docs/appendix/intraday-audit.md §2/§7 item 5). Every
    # signal before this column existed was daily, hence the "1d" default;
    # queries that don't explicitly filter by timeframe should keep
    # defaulting to "1d" too, so adding intraday scoring never silently
    # changes what the existing daily-cadence dashboard shows.
    timeframe: Mapped[str] = mapped_column(String(8), default="1d")
    direction: Mapped[SignalDirection] = mapped_column(Enum(SignalDirection), default=SignalDirection.NO_SIGNAL)
    score: Mapped[float] = mapped_column(Float, default=0)          # 0-100 composite
    confidence: Mapped[float] = mapped_column(Float, default=0)     # 0-100

    # Component breakdown — see roadmap Phase 2 (explainability panel reads these directly)
    catalyst_score: Mapped[float] = mapped_column(Float, default=0)
    technical_score: Mapped[float] = mapped_column(Float, default=0)
    momentum_score: Mapped[float] = mapped_column(Float, default=0)
    volume_score: Mapped[float] = mapped_column(Float, default=0)
    historical_score: Mapped[float] = mapped_column(Float, default=0)
    regime_score: Mapped[float] = mapped_column(Float, default=0)
    risk_score: Mapped[float] = mapped_column(Float, default=0)

    status: Mapped[str] = mapped_column(String(16), default="active")  # active/invalidated/closed
    explanation: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    stock: Mapped["Stock"] = relationship()


class TradeSetup(Base):
    __tablename__ = "trade_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), nullable=False)
    entry_low: Mapped[float] = mapped_column(Float)
    entry_high: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    target_1: Mapped[float] = mapped_column(Float)
    target_2: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    signal: Mapped["Signal"] = relationship()


class SignalOutcome(Base):
    """What happened after a signal: forward returns from the signal day's
    close, and whether its trade setup reached target or stop first. One row
    per evaluated signal (the last daily signal per stock per day), filled
    in by signals/outcomes.py as the horizons pass."""
    __tablename__ = "signal_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), unique=True, nullable=False)
    signal_date: Mapped[str] = mapped_column(String(10), index=True)     # IST trading day, YYYY-MM-DD
    entry_price: Mapped[float] = mapped_column(Float)                     # close of the signal day
    ret_1d: Mapped[float | None] = mapped_column(Float, nullable=True)    # raw returns, not direction-adjusted
    ret_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_result: Mapped[str | None] = mapped_column(String(16), nullable=True)  # target / stop / expired
    setup_bars: Mapped[int | None] = mapped_column(Integer, nullable=True)       # bars until resolved
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    signal: Mapped["Signal"] = relationship()


# ── Historical analogues (Phase 3) ───────────────────────────────────────────

class HistoricalEvent(Base):
    __tablename__ = "historical_events"
    __table_args__ = (
        Index("ix_histevent_stock_type", "stock_id", "event_type"),
        Index("ix_histevent_type_direction_regime", "event_type", "direction", "regime"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32))
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Similarity dimensions (spec §22) beyond event_type — narrows the
    # analogue search to genuinely comparable past setups.
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)   # bullish/bearish/neutral
    regime: Mapped[str | None] = mapped_column(String(24), nullable=True)      # MarketRegime at event time
    price_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_after_15m: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_after_1h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_after_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_after_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_change: Mapped[float | None] = mapped_column(Float, nullable=True)

    stock: Mapped["Stock"] = relationship()


# ── Watchlists (Phase 5 builds the CRUD API on top of this) ─────────────────

class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="My Stocks")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    items: Mapped[list["WatchlistItem"]] = relationship(back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "stock_id", name="uq_watchlist_stock"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id"), nullable=False)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    watchlist: Mapped["Watchlist"] = relationship(back_populates="items")
    stock: Mapped["Stock"] = relationship()


# ── Alerts (Phase 5 builds the evaluation engine on top of this) ────────────

class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    stock_id: Mapped[int | None] = mapped_column(ForeignKey("stocks.id"), nullable=True)  # null = whole universe
    condition: Mapped[dict] = mapped_column(JSON)  # e.g. {"score__gt": 80, "relative_volume__gt": 2}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    stock: Mapped["Stock | None"] = relationship()


class AlertTrigger(Base):
    """One row per (alert, stock, evaluation cycle) match — a bare
    `triggered_at` timestamp on Alert can't say *which* stock matched or
    with what values, which is what "shows up in-app" actually needs."""
    __tablename__ = "alert_triggers"
    __table_args__ = (Index("ix_alerttrigger_alert_created", "alert_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), nullable=False)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    matched_values: Mapped[dict] = mapped_column(JSON)  # snapshot of the fields the condition checked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    alert: Mapped["Alert"] = relationship()
    stock: Mapped["Stock"] = relationship()


# ── The handbook (docs/) ────────────────────────────────────────────────────
# A copy of the markdown handbook for SQL access. docs/*.md and
# docs/book.yaml stay the source of truth; scripts/migrate_docs.py creates
# the tables (db/sql/handbook.sql) and db/docs_sync.py refreshes them.

class DocChapter(Base):
    __tablename__ = "doc_chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)  # relative to docs/
    part: Mapped[str] = mapped_column(String(128))
    part_number: Mapped[int] = mapped_column(Integer)
    number: Mapped[int] = mapped_column(Integer, index=True)       # chapter number across the book
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)                      # full markdown
    content_sha256: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sections: Mapped[list["DocSection"]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan", order_by="DocSection.position")


class DocSection(Base):
    """One `## ` section of a chapter. Position 0 is the text before the
    first `## ` heading (anchor "")."""
    __tablename__ = "doc_sections"
    __table_args__ = (UniqueConstraint("chapter_id", "position", name="uq_docsection_chapter_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("doc_chapters.id", ondelete="CASCADE"),
                                            index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[str] = mapped_column(String(255))                # heading id used in links
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)

    chapter: Mapped["DocChapter"] = relationship(back_populates="sections")
