"""
Shared read-query helpers for Signal rows.

`latest_signal_per_stock` exists because of a real bug found during Phase
6 verification: an earlier version dedup'd "latest signal per stock" in
Python over a `LIMIT recency_window` SQL fetch, breaking out once N
distinct stocks were seen. That silently drops any stock whose latest row
isn't among the most-recently-inserted rows overall — e.g. one stock
re-scored after the others pushes their genuinely-latest signals out of
the window before the per-stock dedup ever reaches them. A live query for
"stocks with unusual volume" returned 2 of 3 qualifying stocks because of
exactly this. Fixed at the SQL level (GROUP BY subquery joined back) so
it's correct regardless of how re-scoring is distributed over time.
"""
from __future__ import annotations
from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from db.models import Signal, Stock


def latest_signal_per_stock(db: Session) -> Query:
    """Query yielding (Signal, symbol) tuples — exactly one row per stock,
    its most recent by timestamp."""
    latest_ts = (
        db.query(Signal.stock_id, func.max(Signal.timestamp).label("max_ts"))
        .group_by(Signal.stock_id)
        .subquery()
    )
    return (
        db.query(Signal, Stock.symbol)
        .join(Stock, Signal.stock_id == Stock.id)
        .join(latest_ts, (Signal.stock_id == latest_ts.c.stock_id) & (Signal.timestamp == latest_ts.c.max_ts))
    )
