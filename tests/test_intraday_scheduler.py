"""Tests for the intraday scheduler track (docs/intraday_gaps.md §6/§7
item 6): opt-in, coexists with the daily jobs, always market-hours-gated,
and calls run_signal_engine/evaluate_alerts with an intraday timeframe
rather than the daily default."""
from __future__ import annotations
from unittest.mock import patch

import pytest

from scheduler import app as scheduler_app
from scheduler import jobs


@pytest.fixture(autouse=True)
def _reset_scheduler():
    scheduler_app.stop_scheduler()
    jobs._LAST_RUN.clear()
    yield
    scheduler_app.stop_scheduler()
    jobs._LAST_RUN.clear()


def test_intraday_jobs_absent_when_intraday_disabled():
    cfg = {"scheduler": {"enabled": True, "intraday_enabled": False}}
    sched = scheduler_app.start_scheduler(cfg)
    try:
        job_ids = {j.id for j in sched.get_jobs()}
        assert "intraday_signal_engine" not in job_ids
        assert "intraday_alert_evaluation" not in job_ids
    finally:
        scheduler_app.stop_scheduler()


def test_intraday_jobs_present_when_intraday_enabled():
    cfg = {"scheduler": {"enabled": True, "intraday_enabled": True}}
    sched = scheduler_app.start_scheduler(cfg)
    try:
        job_ids = {j.id for j in sched.get_jobs()}
        assert {"news_ingest", "signal_engine", "alert_evaluation", "historical_backfill",
                "intraday_signal_engine", "intraday_alert_evaluation"} == job_ids
    finally:
        scheduler_app.stop_scheduler()


def test_intraday_signal_interval_is_independently_configurable():
    cfg = {"scheduler": {
        "enabled": True, "intraday_enabled": True,
        "signal_interval_seconds": 300, "intraday_signal_interval_seconds": 120,
    }}
    sched = scheduler_app.start_scheduler(cfg)
    try:
        daily = sched.get_job("signal_engine")
        intraday = sched.get_job("intraday_signal_engine")
        assert daily.trigger.interval.total_seconds() == 300
        assert intraday.trigger.interval.total_seconds() == 120
    finally:
        scheduler_app.stop_scheduler()


def test_intraday_signal_engine_job_uses_configured_timeframe():
    with patch("scripts.run_signal_engine.run_signal_engine") as mock_run:
        mock_run.return_value = {"universe": 1, "scored": 1, "skipped": 0, "directions": {}}
        run = jobs.intraday_signal_engine_job(lookback_days=5, timeframe="30m")

    assert run.ok is True
    mock_run.assert_called_once_with(limit=None, lookback_days=5, timeframe="30m")


def test_intraday_alert_evaluation_job_uses_configured_timeframe():
    with patch("signals.evaluate_alerts") as mock_eval, \
         patch("utils.telegram_alerts.TelegramAlerter"):
        mock_eval.return_value.alerts_checked = 2
        mock_eval.return_value.triggers = []
        run = jobs.intraday_alert_evaluation_job(timeframe="30m")

    assert run.ok is True
    _, kwargs = mock_eval.call_args
    assert kwargs.get("timeframe") == "30m"


def test_intraday_jobs_default_to_market_hours_guard(monkeypatch):
    calls = []
    monkeypatch.setattr("data_engine.upstox.market_hours.is_market_open", lambda: False)
    guarded = scheduler_app._market_hours_guard("intraday_signal_engine", lambda: calls.append(1))
    guarded()
    assert calls == []  # never runs outside market hours, same as the daily signal/alert jobs
