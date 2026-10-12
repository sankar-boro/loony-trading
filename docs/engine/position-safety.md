# Position Safety

The features in this chapter exist to stop the live bot from losing track of
what it holds: closing intraday positions on time, surviving crashes, agreeing
with the broker, rejecting bad prices and refusing stale tokens. They all live
in `main.py` (`UpstoxTradingBot`) with helpers in the executor and risk
manager.

## Intraday (MIS) squareoff

Upstox force-closes open MIS positions at 15:20 IST at whatever the market
gives. The bot closes them itself at **15:14 IST**:

- **Once per trading day** — the first tick at or after 15:14 triggers
  `_squareoff_mis()`; the date is remembered so it does not repeat, and it
  re-arms the next day.
- **Live**: `executor.squareoff_all_mis()` reads the broker's positions and
  sends a market order to close every MIS position. The bot then removes its
  own tracked positions **without sending a second order** (which would open a
  new position the other way), booking P&L at the last seen price with reason
  `mis_squareoff`.
- **Paper**: each tracked position is closed through a simulated fill.
- Only when `default_product` is `MIS`; delivery (CNC) positions are left
  alone.
- **No new intraday entries after 15:14** — the broker would close them minutes
  later. In practice the entry window (`intraday.entry_end`, 14:45) stops MIS
  entries earlier; see [Intraday Session Controls](intraday-controls.md).
- With exchange-held stops enabled, the bot cancels its broker stop orders
  before the squareoff.

The paper trader (`scripts/paper_trade.py`) has its own equivalent and the
backtester simulates the same cut-off on historical bars.

## One position per symbol

The bot never holds more than one position per symbol:

- A signal in the same direction as an open position is ignored (no
  pyramiding).
- An opposite signal closes the open position (reason `signal_reversal`) and
  the bot stays flat rather than flipping.
- `RiskManager.validate_signal()` rejects any second position in a symbol as a
  safety net for other callers.

## Crash recovery

The bot writes its open positions to `data/live_positions.json` after every
open or close and at least every 5 seconds while ticks arrive — atomically
(write to a temporary file, then rename), so a crash mid-write never leaves a
corrupt file.

```json
{ "source": "main", "mode": "live", "saved_at": 1791545520.4,
  "session_date": "2026-10-09",
  "initial_capital": 500000, "capital": 503120.5, "cash": 431000.0,
  "daily_pnl": 3120.5, "daily_trade_count": 4,
  "positions": [ { "symbol": "RELIANCE", "direction": 1, "entry_price": 2801.5,
                   "size": 25, "stop_loss": 2766.0, "take_profit": 2885.0,
                   "trailing_stop_pct": 0.02, "strategy": "donchian_breakout",
                   "peak_price": 2812.0, "pnl": 262.5, "entry_time": "…",
                   "product": "CNC", "current_price": 2812.0, "unrealised_pnl": 262.5 } ] }
```

On startup it restores from that file, with these rules:

| Situation | Behaviour |
|---|---|
| File written by `paper_trade.py`, or by this bot in another mode | Ignored — paper positions never load into live |
| Same trading day | Positions restored with their current stops; daily P&L and trade count kept |
| Earlier day, MIS position | Dropped — the broker squared it off at 15:20 |
| Earlier day, CNC position | Restored; daily counters start at zero |

The file also carries the intraday session state (trade counts, cooldowns,
halt, pause), recent bot events and the last tick time. The dashboard reads
it for the Positions page, the **Bot** status light and the
[Intraday Desk](../dashboard/intraday-desk.md). See
[Persisted state](intraday-controls.md#persisted-state).

## Broker reconciliation

In live mode the bot compares its book with Upstox at startup and every
`execution.reconcile_interval_sec` (300 s):

1. `executor.fetch_broker_quantities()` reads short-term positions and
   long-term holdings (including T1 shares) and nets them per instrument. It
   **raises on any API error**, so a failed request is never mistaken for an
   empty account; reconciliation simply skips that run.
2. `execution_engine/reconcile.compare_books()` reports:

| Mismatch | Meaning | Action |
|---|---|---|
| `missing_at_broker` | The bot thinks it holds more (in its direction) than Upstox has | Shrink the bot's positions to what Upstox holds — newest first, booked at the last price, **no order sent** — and send an alert. At startup immediately; during the session only after two consecutive checks, so an order still filling is not mistaken for a missing position |
| `untracked_at_broker` | Upstox shows a position opened today that the bot does not track | Alert once per instrument per day; the bot does not take it over |

Upstox holding *more* than the bot in the same direction is not a mismatch —
it may be your own long-term shares. That also means a duplicate fill of a
bot order would not be flagged, which is one reason order placement is never
retried.

## Bad ticks

`_is_sane_tick()` drops prices ≤ 0 and moves larger than
`execution.max_tick_jump_pct` (20 %) from the last accepted price, then accepts
a new level once three consecutive ticks agree within 1 % — see
[The Live Feed](live-feed.md#tick-sanity-check).

## Unfilled and failed orders

Live orders still working after the 30-second status poll are cancelled; a
partial fill is tracked at its filled size. A failed placement is not retried.
See [Execution](execution.md#execute_signal-step-by-step).

## Token checks

At startup the bot computes the token's real expiry (03:30 IST after issue):

- **Live** refuses to start with an expired or missing token.
- **Paper** warns and continues.
- Either mode warns when the token expires within three hours.

See [Connecting to Upstox](../getting-started/upstox-access.md#when-the-daily-token-expires).

## Exchange-held stops and the kill switch

Two more protections are described in
[Intraday Session Controls](intraday-controls.md):
- **exchange-held SL-M stops**, so a position stays protected if the bot
  dies;
- a **kill switch** that flattens everything when the day's realised plus
  unrealised loss reaches `risk.max_daily_drawdown`.

## What is still missing

- Positions opened by hand at the broker are alerted, not adopted.
- A position closed at the broker by hand is detected (as missing) only by
  reconciliation, up to two checks later.
- See [Project Status](../appendix/status.md) for the full list.
