# Alert Evaluation

This chapter covers how alert rules are stored and evaluated
(`signals/alerts.py`). For using them from the dashboard, see
[Watchlists and Alerts](../dashboard/watchlists-alerts.md).

## Conditions

An alert's `condition` is a flat JSON object. Each key is
`<field>__<operator>` and each value is the threshold; every key must match
(logical AND):

```json
{ "score__gte": 75, "catalyst_score__gt": 60, "direction__eq": "bullish" }
```

| Allowed fields | Operators |
|---|---|
| `score`, `confidence`, `catalyst_score`, `technical_score`, `momentum_score`, `volume_score`, `historical_score`, `regime_score`, `risk_score`, `direction` | `gt` (>), `gte` (≥), `lt` (<), `lte` (≤), `eq` (=) |

Only these signal columns can be tested, so an alert cannot reach arbitrary
database state. `validate_condition()` rejects empty conditions, malformed keys
and unknown fields when the alert is created; evaluation also fails closed on
anything malformed or missing (the alert simply does not match). OR logic needs
two alerts.

## Evaluation

`evaluate_alerts(db, notifier=None, timeframe="1d")`:

1. Loads every active alert.
2. For each, takes the **latest signal per stock** for the timeframe — all
   stocks, or the alert's one stock.
3. Compares each signal with the condition; for every match it stores an
   `alert_triggers` row (alert, stock, signal, matched values) and updates the
   alert's `triggered_at`.
4. Commits, then — if the notifier is enabled — sends one message:
   "🔔 N alert(s) triggered" followed by up to ten `name: SYMBOL — {values}` lines.
5. Returns an `EvaluationSummary` (alerts checked, trigger list).

It is plain comparison — no LLM involved.

### Who runs it

| Caller | Timeframe | Notifier |
|---|---|---|
| Scheduler `alert_evaluation` job (every 5 min, market hours) | `1d` | Telegram |
| Scheduler `intraday_alert_evaluation` job (opt-in) | `scheduler.intraday_timeframe` | Telegram |
| `POST /api/alerts/evaluate?timeframe=…` (Alerts page, Intraday Lab) | as requested | Telegram |

### Repeat triggering

Evaluation has no memory of previous matches: while a stock's latest signal
keeps meeting the condition, every run records another trigger and sends
another notification. Because the scheduler re-scores and re-evaluates every
five minutes, a persistent condition notifies every five minutes. Write
conditions around changes you want to hear about, pause alerts you have acted
on, or add a cooldown (see [Project Status](../appendix/status.md)).
