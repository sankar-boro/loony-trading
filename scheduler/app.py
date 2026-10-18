"""BackgroundScheduler wiring (MarketPulse AI Phase 11 — spec §55).

Started/stopped from the FastAPI app lifespan (dashboard/backend/main.py).
Disabled by default (scheduler.enabled in config/settings.yaml) so
importing the app never silently starts hitting live APIs — tests never
import the real app, but a fresh checkout or a one-off script run
shouldn't either.
"""
from __future__ import annotations
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from utils.logger import get_logger
from . import jobs

logger = get_logger("scheduler.app")

_scheduler: Optional[BackgroundScheduler] = None


def _market_hours_guard(name: str, fn):
    """Wrap a job so it's a no-op while the market is closed, per
    scheduler.market_hours_only. News still runs after hours — only
    price-dependent jobs (signals, alerts) are gated."""
    def wrapped():
        from data_engine.upstox.market_hours import is_market_open
        if not is_market_open():
            logger.debug(f"{name}: market closed, skipping")
            return
        fn()
    return wrapped


def start_scheduler(cfg: dict) -> Optional[BackgroundScheduler]:
    global _scheduler
    sched_cfg = cfg.get("scheduler", {})
    if not sched_cfg.get("enabled", False):
        logger.info("Scheduler disabled (scheduler.enabled: false in config)")
        return None

    if _scheduler is not None:
        return _scheduler

    tz = cfg.get("system", {}).get("timezone", "Asia/Kolkata")
    sched = BackgroundScheduler(timezone=tz)

    news_job = jobs.news_ingest_job
    signal_job = jobs.signal_engine_job
    alert_job = jobs.alert_evaluation_job
    if sched_cfg.get("market_hours_only", True):
        signal_job = _market_hours_guard("signal_engine", jobs.signal_engine_job)
        alert_job = _market_hours_guard("alert_evaluation", jobs.alert_evaluation_job)

    sched.add_job(
        news_job, IntervalTrigger(seconds=sched_cfg.get("news_interval_seconds", 60)),
        id="news_ingest", max_instances=1, coalesce=True,
    )
    sched.add_job(
        signal_job, IntervalTrigger(seconds=sched_cfg.get("signal_interval_seconds", 300)),
        id="signal_engine", max_instances=1, coalesce=True,
    )
    sched.add_job(
        alert_job, IntervalTrigger(seconds=sched_cfg.get("alert_interval_seconds", 300)),
        id="alert_evaluation", max_instances=1, coalesce=True,
    )
    sched.add_job(
        lambda: jobs.historical_backfill_job(sched_cfg.get("historical_backfill_min_age_days", 7)),
        CronTrigger(
            hour=sched_cfg.get("historical_backfill_hour", 18),
            minute=sched_cfg.get("historical_backfill_minute", 0),
            timezone=tz,
        ),
        id="historical_backfill", max_instances=1, coalesce=True,
    )

    if sched_cfg.get("ml_retrain_enabled", True):
        sched.add_job(
            lambda: jobs.ml_retrain_job(sched_cfg.get("ml_retrain_days", 730)),
            CronTrigger(
                day_of_week=sched_cfg.get("ml_retrain_day_of_week", "sun"),
                hour=sched_cfg.get("ml_retrain_hour", 6),
                minute=0,
                timezone=tz,
            ),
            id="ml_retrain", max_instances=1, coalesce=True,
        )

    # Opt-in: fitted models change how the bot classifies regimes.
    if sched_cfg.get("regime_refit_enabled", False):
        sched.add_job(
            lambda: jobs.regime_refit_job(sched_cfg.get("regime_refit_days", 1095)),
            CronTrigger(
                day_of_week=sched_cfg.get("regime_refit_day_of_week", "sun"),
                hour=sched_cfg.get("regime_refit_hour", 7),
                minute=0,
                timezone=tz,
            ),
            id="regime_refit", max_instances=1, coalesce=True,
        )

    # Intraday signal/alert jobs — separate opt-in track, coexisting with
    # the daily jobs above rather than replacing them (docs/appendix/intraday-audit.md
    # §6/§7 item 6). Always market-hours-gated regardless of
    # market_hours_only: an intraday bar is meaningless once the session
    # is closed, unlike news.
    if sched_cfg.get("intraday_enabled", False):
        intraday_tf = sched_cfg.get("intraday_timeframe", "30m")
        intraday_job = _market_hours_guard(
            "intraday_signal_engine",
            lambda: jobs.intraday_signal_engine_job(
                lookback_days=sched_cfg.get("intraday_lookback_days", 5),
                timeframe=intraday_tf,
            ),
        )
        intraday_alert_job = _market_hours_guard(
            "intraday_alert_evaluation",
            lambda: jobs.intraday_alert_evaluation_job(timeframe=intraday_tf),
        )
        sched.add_job(
            intraday_job,
            IntervalTrigger(seconds=sched_cfg.get("intraday_signal_interval_seconds", 900)),
            id="intraday_signal_engine", max_instances=1, coalesce=True,
        )
        sched.add_job(
            intraday_alert_job,
            IntervalTrigger(seconds=sched_cfg.get("intraday_alert_interval_seconds", 900)),
            id="intraday_alert_evaluation", max_instances=1, coalesce=True,
        )

    sched.start()
    _scheduler = sched
    logger.info(
        f"Scheduler started: news={sched_cfg.get('news_interval_seconds', 60)}s, "
        f"signals={sched_cfg.get('signal_interval_seconds', 300)}s, "
        f"alerts={sched_cfg.get('alert_interval_seconds', 300)}s, "
        f"historical backfill daily at {sched_cfg.get('historical_backfill_hour', 18):02d}:"
        f"{sched_cfg.get('historical_backfill_minute', 0):02d} {tz}"
        + (f", intraday({sched_cfg.get('intraday_timeframe', '30m')})="
           f"{sched_cfg.get('intraday_signal_interval_seconds', 900)}s"
           if sched_cfg.get("intraday_enabled", False) else "")
    )
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


def get_status() -> dict:
    running = _scheduler is not None and _scheduler.running
    next_runs = {}
    if running:
        for job in _scheduler.get_jobs():
            next_runs[job.id] = job.next_run_time.isoformat() if job.next_run_time else None
    return {
        "running": running,
        "next_runs": next_runs,
        "last_runs": jobs.last_runs(),
    }
