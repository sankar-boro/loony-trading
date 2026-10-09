"""Tests for the Phase 11 scheduler (spec §55): job wiring, market-hours
gating, disabled-by-default config, and status reporting."""
from __future__ import annotations

import pytest

from scheduler import app as scheduler_app
from scheduler import jobs


@pytest.fixture(autouse=True)
def _reset_scheduler():
    """Every test starts and ends with no scheduler running — the module
    keeps a process-wide singleton, so leaking a started scheduler across
    tests would make later tests order-dependent."""
    scheduler_app.stop_scheduler()
    jobs._LAST_RUN.clear()
    yield
    scheduler_app.stop_scheduler()
    jobs._LAST_RUN.clear()


def test_scheduler_disabled_by_default_returns_none():
    sched = scheduler_app.start_scheduler({"scheduler": {"enabled": False}})
    assert sched is None
    assert scheduler_app.get_status()["running"] is False


def test_scheduler_starts_and_schedules_all_jobs_when_enabled():
    cfg = {"scheduler": {"enabled": True}, "system": {"timezone": "Asia/Kolkata"}}
    sched = scheduler_app.start_scheduler(cfg)
    try:
        assert sched is not None
        assert sched.running
        job_ids = {j.id for j in sched.get_jobs()}
        assert job_ids == {"news_ingest", "signal_engine", "alert_evaluation",
                           "historical_backfill", "ml_retrain"}
    finally:
        scheduler_app.stop_scheduler()


def test_ml_retrain_job_can_be_disabled():
    cfg = {"scheduler": {"enabled": True, "ml_retrain_enabled": False}}
    sched = scheduler_app.start_scheduler(cfg)
    try:
        assert "ml_retrain" not in {j.id for j in sched.get_jobs()}
    finally:
        scheduler_app.stop_scheduler()


def test_start_scheduler_is_idempotent():
    cfg = {"scheduler": {"enabled": True}}
    first = scheduler_app.start_scheduler(cfg)
    second = scheduler_app.start_scheduler(cfg)
    assert first is second


def test_stop_scheduler_clears_status():
    scheduler_app.start_scheduler({"scheduler": {"enabled": True}})
    scheduler_app.stop_scheduler()
    status = scheduler_app.get_status()
    assert status["running"] is False
    assert status["next_runs"] == {}


def test_custom_intervals_applied(monkeypatch):
    cfg = {"scheduler": {
        "enabled": True, "news_interval_seconds": 15, "signal_interval_seconds": 45,
        "alert_interval_seconds": 90, "market_hours_only": False,
    }}
    sched = scheduler_app.start_scheduler(cfg)
    try:
        news_job = sched.get_job("news_ingest")
        assert news_job.trigger.interval.total_seconds() == 15
        signal_job = sched.get_job("signal_engine")
        assert signal_job.trigger.interval.total_seconds() == 45
        alert_job = sched.get_job("alert_evaluation")
        assert alert_job.trigger.interval.total_seconds() == 90
    finally:
        scheduler_app.stop_scheduler()


def test_market_hours_guard_skips_when_market_closed(monkeypatch):
    calls = []
    monkeypatch.setattr("data_engine.upstox.market_hours.is_market_open", lambda: False)
    guarded = scheduler_app._market_hours_guard("test_job", lambda: calls.append(1))
    guarded()
    assert calls == []


def test_market_hours_guard_runs_when_market_open(monkeypatch):
    calls = []
    monkeypatch.setattr("data_engine.upstox.market_hours.is_market_open", lambda: True)
    guarded = scheduler_app._market_hours_guard("test_job", lambda: calls.append(1))
    guarded()
    assert calls == [1]


def test_run_tracked_records_success():
    run = jobs._run_tracked("demo_job", lambda: {"ok": True})
    assert run.ok is True
    assert jobs.last_runs()["demo_job"]["ok"] is True
    assert jobs.last_runs()["demo_job"]["detail"] == {"ok": True}


def test_run_tracked_records_failure_without_raising():
    def _boom():
        raise ValueError("simulated failure")
    run = jobs._run_tracked("failing_job", _boom)
    assert run.ok is False
    assert "simulated failure" in run.detail
    assert jobs.last_runs()["failing_job"]["ok"] is False


def test_scheduler_status_endpoint():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from dashboard.backend.routers.scheduler import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    resp = client.get("/api/scheduler/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "running" in body
    assert "next_runs" in body
    assert "last_runs" in body
