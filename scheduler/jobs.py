"""Scheduled job bodies (MarketPulse AI Phase 11 — spec §55).

Each job wraps an existing, independently-runnable pipeline entry point
(the same ones the CLI scripts and on-demand API endpoints use) with
error isolation: a failure in one job must never take down the
scheduler or block the next job from running, since APScheduler's
default behaviour is to just log and continue — this module makes that
explicit and records the outcome for /api/scheduler/status.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from db.base import session_scope
from utils.logger import get_logger

logger = get_logger("scheduler.jobs")


@dataclass
class JobRun:
    name: str
    started_at: str
    ok: bool
    detail: dict | str
    duration_ms: float


# Rolling last-run status per job name, surfaced via /api/scheduler/status.
_LAST_RUN: dict[str, JobRun] = {}


def _run_tracked(name: str, fn: Callable[[], dict]) -> JobRun:
    start = datetime.now(timezone.utc)
    t0 = start.timestamp()
    try:
        detail = fn()
        run = JobRun(name=name, started_at=start.isoformat(), ok=True,
                     detail=detail, duration_ms=round((datetime.now(timezone.utc).timestamp() - t0) * 1000, 1))
        logger.info(f"job {name} ok: {detail}")
    except Exception as e:
        run = JobRun(name=name, started_at=start.isoformat(), ok=False,
                     detail=str(e), duration_ms=round((datetime.now(timezone.utc).timestamp() - t0) * 1000, 1))
        logger.error(f"job {name} failed: {e}")
    _LAST_RUN[name] = run
    return run


def last_runs() -> dict[str, dict]:
    return {name: run.__dict__ for name, run in _LAST_RUN.items()}


# ── Job bodies ────────────────────────────────────────────────────────────

def news_ingest_job() -> JobRun:
    def _do() -> dict:
        from data_engine.news.pipeline import NewsIngestionPipeline
        with session_scope() as db:
            return NewsIngestionPipeline().run_once(db, limit=20)
    return _run_tracked("news_ingest", _do)


def signal_engine_job(limit: int | None = None) -> JobRun:
    def _do() -> dict:
        from scripts.run_signal_engine import run_signal_engine
        return run_signal_engine(limit=limit)
    return _run_tracked("signal_engine", _do)


def alert_evaluation_job() -> JobRun:
    def _do() -> dict:
        from signals import evaluate_alerts
        from utils.telegram_alerts import TelegramAlerter
        with session_scope() as db:
            summary = evaluate_alerts(db, notifier=TelegramAlerter())
        return {"alerts_checked": summary.alerts_checked, "triggers": len(summary.triggers)}
    return _run_tracked("alert_evaluation", _do)


def historical_backfill_job(min_age_days: int = 7) -> JobRun:
    def _do() -> dict:
        from scripts.backfill_historical_events import run_organic_backfill
        created = run_organic_backfill(min_age_days=min_age_days)
        return {"created": created}
    return _run_tracked("historical_backfill", _do)
