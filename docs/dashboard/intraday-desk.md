# Intraday Desk

The Intraday Desk (`/desk`, `pages/IntradayDesk.tsx`) is the page to keep
open while the bot trades. It shows:
- where the session stands;
- how much of the day's loss budget is used;
- what the bot holds and has done today, and why it skipped signals.

Its buttons pause entries, resume them, or flatten everything.

It refreshes every 5 seconds from one endpoint, `GET /api/intraday/desk`.
The data comes from files the live bot writes (`python main.py --mode paper` or
`--mode live`); the rules behind it are in
[Intraday Session Controls](../engine/intraday-controls.md).

The [Intraday Lab](intraday-lab.md) is a different page, for intraday
*research* (signal scans and alert checks).

## Header

| Item | Shows |
|---|---|
| Date, time, mode | IST clock and `PAPER` or `LIVE` (red) |
| Session phase | Pre-open, Opening, Entry window, Manage only, Squareoff, Closed, Weekend or Exchange holiday |
| Bot status | Trading; Entries paused by operator; Halted — *reason*; No market data for *n* min; or Bot stopped |
| Feed | Seconds since the last tick; "broker-held stops on" when exchange stops are enabled |

The phases come from the clock and your entry window:

| Phase | IST | What the bot does |
|---|---|---|
| Pre-open | before 09:15 | Nothing to do |
| Opening | 09:15 → `entry_start` | Manages positions; no new MIS entries |
| Entry window | `entry_start` → `entry_end` | Takes new entries |
| Manage only | `entry_end` → 15:14 | Exits only; no new MIS entries |
| Squareoff | 15:14 → 15:30 | MIS positions closed |
| Closed | after 15:30 | — |

"Bot stopped" means the bot has not rewritten its state file for 30 seconds.
"No market data" appears when the bot is running in market hours but no tick
has arrived for two minutes.

## Controls

| Button | When shown | Effect |
|---|---|---|
| **Pause entries** | Not paused or halted | No new entries. Open positions keep their stops and targets |
| **Resume entries** / **Clear halt & resume** / **Re-enable strategies** | Paused, halted, or a strategy switched off | Entries allowed again; clears a kill-switch or profit-lock halt and turns switched-off strategies back on for today |
| **Flatten all** | Any open position | Closes every position at market (reason `operator_flatten`) |

Each button asks for confirmation, then calls `POST /api/intraday/control`.
That writes `data/bot_control.json`, and the bot acts on its next tick. When
the bot is not running, the page says so: a pause is kept for the next start,
but a flatten clicked while the bot is stopped is ignored on purpose. See
[Operator controls](../engine/intraday-controls.md#operator-controls).

## Session timeline

A bar from 09:15 to 15:30. The entry window is shaded green, the squareoff
period red, and a white line marks now. On a trading day the right side
counts down the minutes to the last entry and to the 15:14 squareoff.

## KPI cards

| Card | Meaning |
|---|---|
| Day P&L | Realised (closed today) + unrealised (open positions at last price), with both parts below |
| Loss budget used | Day loss as a % of the kill-switch limit (`risk.max_daily_drawdown` × capital). The meter turns amber at 50 % and red at 80 % |
| Entries today | Filled entries against `max_trades_per_day`, with the per-symbol cap |
| Open positions | Count; with exchange stops on, how many have one at the broker |
| Closed trades | Count of trades closed today and how many won |

## P&L today

A minute-by-minute curve of day P&L, from `data/intraday_pnl.jsonl`. A dashed
red line marks the kill-switch level and, if a profit lock is set, a green
one marks it. The line only appears when it is inside the chart's range. The
curve starts when the bot does; before that the panel says it will fill in.

Next to it, **By strategy** totals today's closed trades per strategy: wins
over trades and net P&L, best first. A strategy switched off by its
[loss limits](../engine/intraday-controls.md#strategy-limits) is marked
**● off**, with the reason listed under the table; the panel header shows
the limits.

## Open positions

Symbol (strategy and product), side, quantity, entry, last price, stop,
target and unrealised P&L. With exchange stops enabled, a **Broker stop**
column shows *held* (with the order id on hover) or *missing*. Missing means
the stop is only held in memory; see
[Exchange-held stops](../engine/intraday-controls.md#exchange-held-stops).

Symbols cooling down after a stop-out are listed under the table with the
time the cooldown ends.

## Today's trades and bot events

**Today's trades** lists trades closed today (newest first) from
`logs/trades.jsonl`: time, symbol and strategy, side, entry, exit, reason and
P&L.

**Bot events** lists today's events, newest first:

- entries and exits;
- signals the session rules blocked, with the reason (for example
  "INFY BUY (orb) not taken — INFY cooling down until 13:20");
- halts, flattens, operator actions, squareoff;
- feed alerts and exchange-stop errors.

The event kinds are listed under
[Bot events](../engine/intraday-controls.md#bot-events).

## When the bot is not running

The page still loads. It shows the session clock, limits from
`config/settings.yaml` and any trades already logged today; positions and
events are empty. State left from an earlier day is not shown as today's.
