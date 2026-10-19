# Intraday Session Controls

Per-trade risk checks ([Risk Management](risk-management.md)) decide whether
*one* signal is acceptable. Intraday trading also needs rules about the
*session*: when entries are allowed, how many, when to stop for the day, and a
way for you to step in. This chapter covers those rules, the operator
controls behind the [Intraday Desk](../dashboard/intraday-desk.md), and the
monitoring that goes with them.

| Piece | File |
|---|---|
| Session rules | `risk_manager/intraday_guard.py` (`IntradayGuard`) |
| Operator controls | `utils/bot_control.py` |
| Exchange-held stops | `execution_engine/upstox_executor.py` |
| Bar recording | `data_engine/live_bars.py` (`BarRecorder`) |
| Wiring | `main.py` (`UpstoxTradingBot`) |

All of it applies to the live bot (`python main.py --mode paper|live`). The
standalone paper trader `scripts/paper_trade.py` does not use it.

## Order of checks for a new entry

When a bar closes and the strategies produce a signal, the bot runs these
checks in order. The first one that fails stops the entry:

1. MIS squareoff time (15:14 IST) has not passed.
2. The best signal is a BUY or SELL.
3. No open position in that symbol in the same direction. An opposite signal
   closes the position instead; see [Position Safety](position-safety.md#one-position-per-symbol).
4. A SELL on a flat symbol needs a product that can hold a short (MIS);
   see [Shorts need MIS](execution.md#shorts-need-mis).
5. **Session rules** (`IntradayGuard.can_enter`), in this order:
   operator pause → day halted → entry window (MIS only) → daily trade
   cap → per-symbol trade cap → cooldown → the signal's strategy switched
   off by its loss limits.
6. The symbol's sector is below its exposure cap
   ([Sector exposure cap](risk-management.md#sector-exposure-cap)).
7. Not correlated with another open position (`portfolio.correlation_limit`, 0.7).
8. `RiskManager.validate_signal`: concurrent positions, realised daily loss,
   minimum confidence (0.5) and the sector cap. The size is then trimmed to
   the sector's remaining room.

When a session rule blocks a signal, the bot logs a `block` event naming the
rule. It logs it once per symbol per reason, not on every bar.

## Session rules

Settings live under `intraday:` in `config/settings.yaml`:

| Rule | Setting (default) | Behaviour |
|---|---|---|
| Entry window | `entry_start` (`"09:30"`), `entry_end` (`"14:45"`) | No new **MIS** entries outside the window. The first 15 minutes after the open are skipped because of opening noise. The 14:45 cut-off leaves 30 minutes for a trade to work before the 15:14 squareoff. CNC (delivery) entries ignore the window |
| Daily trade cap | `max_trades_per_day` (`20`) | Entries across all symbols per day. `0` means no cap |
| Per-symbol cap | `max_trades_per_symbol` (`3`) | Entries in one symbol per day. Stops the bot churning one stock |
| Cooldown | `cooldown_minutes_after_stop` (`30`) | After a **stop-loss** exit, no new entry in that symbol for this long. Other exit reasons do not start a cooldown |
| Kill switch | `risk.max_daily_drawdown` (`0.05`), `kill_switch.flatten_on_daily_loss` (`true`) | See below |
| Profit lock | `profit_lock_pct` (`0.0`, off) | See below |
| Strategy limits | `strategy_limits.max_daily_loss_pct` (`0.01`), `strategy_limits.max_consecutive_losses` (`4`) | See below |

Only **filled** entries count towards the caps; a rejected or unfilled order
does not.

### Kill switch

On every tick the bot adds the day's realised P&L to the unrealised P&L of
the open positions, marked at their last price. Once that total falls to
−`max_daily_drawdown` × initial capital (₹25,000 on ₹5 lakh at 5 %):

1. The day is **halted**: no new entries for the rest of the day.
2. With `flatten_on_daily_loss: true`, every open position is closed at
   market (reason `kill_switch`), CNC included.
3. A `halt` event is logged and a notification sent.

The switch fires once a day. It runs alongside the `RiskManager` daily-loss
check, which counts realised losses only. The kill switch also counts open
losses, so a large losing position can trip it before any trade has closed.

### Profit lock

With `profit_lock_pct` above zero (for example `0.01`), the day is halted once
day P&L reaches that fraction of capital. Open positions are kept and their
stops keep trailing. The bot just stops taking new risk on a good day.

### Strategy limits

Every closed trade is booked against the strategy that opened it. A
strategy is **switched off for the rest of the day** when either:

- its realised loss today reaches `strategy_limits.max_daily_loss_pct` ×
  capital (₹5,000 on ₹5 lakh at 1 %); or
- it loses `strategy_limits.max_consecutive_losses` trades in a row (a
  winning trade resets the count).

The other strategies keep trading. The bot logs a `halt` event ("Strategy
orb switched off for the day — 4 losing trades in a row") and sends a
notification. Later signals from that strategy are blocked with a `block`
event. **Resume** on the Intraday Desk turns switched-off strategies back
on. Set either limit to `0` to disable it.

### A new day

On the first tick of a new trading day, the caps, cooldowns, strategy
limits and any halt reset. An operator **pause** does not reset; it lasts
until you resume.

## Operator controls

The dashboard and the bot are separate processes. Commands go through a small
file, `data/bot_control.json`:

```json
{ "paused": false, "flatten_id": "3f9a1c2e", "resume_id": "b71d0e44", "updated_at": 1791545520.0 }
```

| Action | Written by `write_control()` | The bot, on its next tick |
|---|---|---|
| `pause` | `paused: true` | Blocks new entries. Open positions keep their stops and targets |
| `resume` | `paused: false`, new `resume_id` | Allows entries again **and clears a kill-switch or profit-lock halt**, and turns strategies switched off by their limits back on |
| `flatten` | new `flatten_id` | Closes every open position at market, reason `operator_flatten` |

How a request is executed exactly once:

- The bot polls the file on each tick, re-reading it only when its
  modification time changes.
- It stores the last `flatten_id` / `resume_id` it acted on in
  `data/live_positions.json`, so a restart does not repeat a flatten.
- At startup, any ids already in the file count as handled, so a flatten
  clicked yesterday never fires today. The `paused` flag *is* honoured at
  startup.

Commands only take effect while ticks arrive. Outside market hours, a command
waits until the next tick.

The Intraday Desk buttons call `POST /api/intraday/control`. Scripts can
write the file directly:

```python
from utils.bot_control import write_control
write_control("pause")
```

## Exchange-held stops

The bot normally holds stops in memory and sends a market order when a tick
crosses one. If the bot crashes, loses its network connection or the feed
stops, those stops do nothing. With `intraday.exchange_stops: true` (live mode
only; off by default) every position also gets a **stop at the broker**:

| Product | Broker stop | Why |
|---|---|---|
| MIS | Stop-loss-market (SL-M) order, DAY validity | Gone with the position at the squareoff |
| CNC | [GTT](execution.md#gtt-orders): sell `BELOW` the stop (buy `ABOVE` for a short) | A DAY order expires at the close and would leave a delivery position unprotected overnight; a GTT persists |

A SELL GTT against delivery holdings needs the account's eDIS or DDPI
authorisation. Without it, placement fails and the Intraday Desk shows the
stop as *missing*.

How the broker stop is handled:

- **Placed** right after an entry fills, for the whole quantity, at
  `stop_loss` rounded to the tick size, product as configured, tag
  `loony-stop`. At startup and after each reconciliation, any position
  without one gets one.
- **Trailed**: when the in-memory trailing stop moves by at least 0.1 % (and
  one tick), the order's trigger is modified to match.
- **Before any close** (target, reversal, kill switch, flatten), the bot first
  asks for the stop order's status:
  - **Already filled**: the broker closed the position. The bot books the
    exit at the stop's average price (`stop_loss (exchange)`) and sends no
    second order.
  - **Still open**: the stop is cancelled, then the closing order is sent.
    If the cancel fails, the bot does **not** send the close, because both
    could fill and leave a position open the other way. It logs an `error`
    event and alerts you, and the next tick tries again.
- **MIS squareoff** cancels all bot stops first, then the broker-side
  squareoff runs.

The Intraday Desk shows each position's broker stop as *held* or *missing*.
A missing stop means placement failed: the position is still protected in
memory, but not at the broker.

Two caveats:
- **Restart after a crash**: positions restored from an earlier day lose
  their SL-M order ids (DAY orders expire), and new stops are placed after
  the first reconciliation. GTT ids are kept, because GTTs persist; on the
  same day all ids are kept.
- **A GTT that has executed** disappears from Upstox's GTT list. The bot then
  checks the broker's holdings: if the position is gone, the stop executed
  and the exit is booked at the trigger price; if it is still held, the GTT
  was cancelled elsewhere.
- **Paper mode** never places exchange stops.

## Monitoring

### Bot events

The bot keeps the last 100 events in memory and saves the last 50 to
`data/live_positions.json` for the dashboard:

| Kind | Written when |
|---|---|
| `entry` | An entry filled |
| `exit` | A position closed (with reason and P&L) |
| `block` | A session rule refused a signal |
| `halt` | Kill switch, profit lock, or a strategy switched off by its limits |
| `flatten` | Positions flattened (operator or kill switch) |
| `control` | Pause, resume or halt cleared |
| `squareoff` | MIS squareoff ran |
| `heartbeat` | Market data stopped, or resumed |
| `error` | An exchange stop could not be placed or cancelled |

`halt`, `flatten` (when something was closed), `error` and `heartbeat` events
also go out as notifications; see [Notifications](../operations/notifications.md).

### Feed heartbeat

During market hours a background task checks every 30 seconds when the last
tick arrived. If nothing has arrived for `heartbeat_minutes` (5), the bot
sends one alert. When ticks return, it logs "Market data resumed". Without
ticks, stops are not checked and commands are not read, so treat this alert
as urgent. Exchange-held stops still protect open positions.

### Minute P&L log

Once a minute, on the first tick of that minute, the bot appends one line to
`data/intraday_pnl.jsonl`:

```json
{"ts": "2026-10-12T11:04:00+05:30", "realised": 1190.0, "unrealised": 358.0, "total": 1548.0, "open_positions": 2}
```

The Intraday Desk draws today's rows as the P&L curve.

## Recording live bars

Every tick feeds the 1-minute bar aggregator. With `intraday.record_bars:
true` (the default), each finished bar is appended to
`data/live_bars/<YYYY-MM-DD>/<SYMBOL>.csv` (IST date):

```
ts,open,high,low,close,volume
2026-10-12T03:45:00+00:00,4012.5,4015.0,4010.1,4013.8,1520
```

On some accounts the Upstox historical API refuses 5- and 15-minute candles
(see [Market Data](market-data.md)), so recording is the way to collect
fine-grained intraday history. Load it with
`BarRecorder().load("TCS", "5m", days=10)`. Bars are resampled within each
session and never across two days. You can also backtest on it directly:

```bash
python scripts/backtest_runner.py --source recorded --timeframe 5m --product MIS --symbol TCS
```

## Persisted state

The guard's counters are saved with the positions under `"intraday"` in
`data/live_positions.json`. A restart on the same day keeps the trade counts,
cooldowns, strategy results, halt and pause; a state file from an earlier day
is ignored. See
[Position Safety](position-safety.md#crash-recovery) for the rest of the file.

```json
"intraday": { "session_date": "2026-10-12", "entry_start": "09:30", "entry_end": "14:45",
              "in_entry_window": true, "max_trades_per_day": 20, "max_trades_per_symbol": 3,
              "trades_today": 7, "trades_by_symbol": {"TCS": 2, "INFY": 1},
              "cooldowns": {"INFY": "2026-10-12T13:20:00+05:30"},
              "max_daily_loss_pct": 0.05, "profit_lock_pct": 0.0,
              "halted": false, "halt_reason": "", "paused": false,
              "strategy_max_daily_loss_pct": 0.01, "strategy_max_consecutive_losses": 4,
              "strategy_pnl": {"orb": -5480.0, "vwap_reversion": 870.0},
              "strategy_streak": {"orb": 2, "vwap_reversion": 0},
              "strategies_off": {"orb": "lost ₹5,480 today (limit 1.0%)"} },
"events": [ … ], "last_tick_at": 1791545520.4, "exchange_stops": false,
"handled_control": { "flatten_id": "3f9a1c2e", "resume_id": null }
```
