# Intraday Lab

The Intraday Lab (`/intraday`, `pages/Intraday.tsx`) gives buttons for the
intraday tools that otherwise need the command line or the scheduler:
scoring composite signals on intraday bars, evaluating alerts against those
signals, and checking the scheduler. Everything it writes is tagged with its
timeframe, so the daily Signals and Alerts pages are unaffected.

## Run an intraday scan

| Field | Meaning | Default |
|---|---|---|
| Symbols | Comma-separated; blank means "the first *Limit* stocks of the universe" | blank |
| Timeframe | `30m` or `1h` | `30m` |
| Lookback days | History to fetch | 5 |
| Limit | Stocks to scan when Symbols is blank | 5 |

**▷ Run Scan** posts to `POST /api/signals/intraday-scan`, which runs the same
`run_signal_engine()` function as the CLI and scheduler and stores `Signal`
rows tagged with the timeframe. The request blocks until the scan finishes,
so keep the symbol count small. The result shows how many symbols were scored
and skipped, and a table of symbol, direction, score and confidence.

Why not 5 or 15 minutes: on the Upstox account this was built against, the
historical-candle API returns HTTP 400 for 5-minute and 15-minute intervals,
while 30-minute and 60-minute work. See [Market Data](../engine/market-data.md).

View the stored results on the [Signals](signals.md) page with the 30 min or
1 hour timeframe selected.

## Evaluate alerts at an intraday timeframe

Runs every active alert against the latest signal of the chosen timeframe
(`POST /api/alerts/evaluate?timeframe=30m`) and lists the triggers. Run a scan
first, or nothing will match.

## Scheduler status

A table from `GET /api/scheduler/status` (every 15 s): each scheduled job, its
next run time and its last run (time, success or failure, and a summary such as
"5 scored"). Intraday jobs appear only when `scheduler.intraday_enabled` is
true. See [The Scheduler](../marketpulse/scheduler.md).
