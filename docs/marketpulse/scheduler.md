# The Scheduler

`scheduler/` keeps MarketPulse fresh without anyone pressing buttons: it
ingests news, re-scores the universe, evaluates alerts, backfills history and
retrains the ML model on a timetable. It is an APScheduler
`BackgroundScheduler` running inside the dashboard backend process.

## Turning it on

It is **off by default**, so that starting the backend never silently starts
calling paid APIs:

```yaml
scheduler:
  enabled: true
```

The FastAPI app's lifespan (`dashboard/backend/main.py`) calls
`start_scheduler(settings)` on startup and `stop_scheduler()` on shutdown, so
restart the backend after changing the setting. Times are in
`system.timezone` (Asia/Kolkata).

> **Run one backend process.** Each process starts its own scheduler. The
> Docker Compose file runs uvicorn with `--workers 2`, which would run every
> job twice (duplicate signals, duplicate alert messages). Use one worker when
> the scheduler is enabled — see [Deployment](../operations/deployment.md).

## Jobs

| Job id | When | Does | Config keys |
|---|---|---|---|
| `news_ingest` | every 60 s, always | One [news pipeline](news-pipeline.md) pass, 20 articles | `news_interval_seconds` |
| `signal_engine` | every 300 s, market hours* | [Score the whole universe](composite-signals.md) on daily bars | `signal_interval_seconds` |
| `alert_evaluation` | every 300 s, market hours* | [Evaluate alerts](watchlists-alerts.md) against daily signals, notify via Telegram | `alert_interval_seconds` |
| `historical_backfill` | daily 18:00 | [Organic analogue backfill](historical-analogues.md) for events ≥ 7 days old | `historical_backfill_hour`, `_minute`, `_min_age_days` |
| `ml_retrain` | Sundays 06:00 | [Gated ML retrain](../engine/machine-learning.md#weekly-retraining) — replaces the model only if it beats the baselines; never enables it | `ml_retrain_enabled`, `ml_retrain_day_of_week`, `ml_retrain_hour`, `ml_retrain_days` |
| `intraday_signal_engine` | every 900 s, market hours (opt-in) | Score the universe on `intraday_timeframe` bars | `intraday_enabled`, `intraday_timeframe`, `intraday_signal_interval_seconds`, `intraday_lookback_days` |
| `intraday_alert_evaluation` | every 900 s, market hours (opt-in) | Evaluate alerts against intraday signals | `intraday_alert_interval_seconds` |

\* Gated by `market_hours_only` (default true): outside NSE hours these jobs
return immediately. News ingestion is never gated. The intraday jobs are always
gated, since an intraday bar means nothing once the session has closed.

Every job is registered with `max_instances=1` and `coalesce=True`: a slow run
is never overlapped by the next one, and missed runs collapse into a single
catch-up run.

## Error isolation and status

Each job body (`scheduler/jobs.py`) runs inside `_run_tracked()`, which catches
any exception, logs it and records the outcome, so one failing job never stops
the scheduler or the other jobs. The last run of each job is kept in memory:

```bash
curl localhost:8000/api/scheduler/status
```

```json
{ "running": true,
  "next_runs": { "signal_engine": "2026-10-09T10:35:00+05:30", … },
  "last_runs": { "signal_engine": { "name": "signal_engine", "started_at": "…", "ok": true,
                                    "detail": { "scored": 88, … }, "duration_ms": 41230.5 } } }
```

The [Intraday Lab](../dashboard/intraday-lab.md) shows this as a table.
`last_runs` is per process and resets on restart.

## Choosing intervals

- **News**: NewsAPI's free tier allows 100 requests a day; at 60 s it is
  exhausted in under two hours. Use 900 s or more on the free tier.
- **Signals**: scoring 91 stocks makes up to 91 candle requests. Daily candles
  are cached by `UpstoxDataEngine`, so 5-minute runs mostly hit the cache — but
  the score changes little within a day on daily bars, so 15–30 minutes is
  usually enough.
- **Alerts**: run right after signals (same interval); faster gains nothing.
- **Intraday**: keep the interval near the bar size (900 s for 30-minute
  bars). Upstox returns HTTP 400 for 5- and 15-minute historical candles on
  some accounts, hence the 30-minute default.

## Adding a job

1. Write a function in `scheduler/jobs.py` that wraps your work in
   `_run_tracked("my_job", _do)` where `_do()` returns a small summary dict.
2. Register it in `start_scheduler()` (`scheduler/app.py`) with an
   `IntervalTrigger` or `CronTrigger`, `id="my_job"`, `max_instances=1`,
   `coalesce=True`, wrapping it in `_market_hours_guard()` if it needs prices.
3. Add any settings under `scheduler:` in `config/settings.yaml`, and update
   the job-id expectations in `tests/test_scheduler.py`.
