# What's Missing for Real Intraday Trading

> **Status: all six gaps below are now fixed.** This doc originally shipped as a
> pre-fix audit; it's kept as-is (findings intact, verified against the code at the
> time) with a **✅ FIXED** note added to the top of each section pointing at what
> changed and where. See §7 for the roadmap that was executed and
> [`docs/trading_playbook.md`](trading_playbook.md) for how to actually use the
> intraday path day to day.

An evidence-based audit, not a guess. Every claim below is backed by a specific
file/line reference verified against the current code — where something turned out
to already exist (and an older doc claimed otherwise), that's called out explicitly
rather than silently repeated.

**Verdict up front (at the time of the audit):** this codebase had two layers with
very different intraday readiness. The **original bot** (`main.py`,
`execution_engine/`, `risk_manager/`) had real intraday bones — a WebSocket tick
feed, MIS auto-squareoff, per-tick stop checks — but one severe,
previously-undiscovered bug defeated the purpose of all of it (§1). The
**MarketPulse AI layer** built this session (composite signals, alerts, portfolio
risk, the scheduler) was daily-bar-only by design, full stop (§2). Both are now
addressed — see the fix notes in each section.

---

## Contents

- [1. The live tick loop never updates its own data (severe)](#1-the-live-tick-loop-never-updates-its-own-data-severe)
- [2. The MarketPulse AI layer is hardcoded to daily bars](#2-the-marketpulse-ai-layer-is-hardcoded-to-daily-bars)
- [3. Session-boundary blindness](#3-session-boundary-blindness)
- [4. Blocking I/O on the event loop](#4-blocking-io-on-the-event-loop)
- [5. Data/infra limits](#5-datainfra-limits)
- [6. What actually already works](#6-what-actually-already-works)
- [7. Fix roadmap, prioritized](#7-fix-roadmap-prioritized)
- [8. Bottom line](#8-bottom-line)

---

## 1. The live tick loop never updates its own data (severe)

> ✅ **FIXED.** New `data_engine/live_bars.py` (`LiveBarAggregator`) turns the feed's
> per-tick candle data into finalized 1-minute bars and resamples to any coarser
> timeframe. `main.py`'s `_on_tick` now feeds it, refreshes `_df_cache` via
> `_refresh_live_df()` on every real bar close (replacing the old ~15-tick guess),
> and only re-scores strategies against that fresh data. 16 tests in
> `tests/test_live_bars.py` and `tests/test_bot_live_refresh.py`.

This is the single most important finding in this document.

`main.py`'s live/paper WebSocket loop (`Bot._on_tick`, `main.py:203-263`) receives a
real-time tick from `UpstoxFeed`, updates the live price for P&L marking and
stop-loss checks, and — every ~15 ticks — calls:

```python
df = self._df_cache.get(symbol) or self._df_cache.get(f"{symbol}_{self.intraday_tf}")
...
signals = self.meta_engine.generate_signals(symbol, df)
```

`self._df_cache` is populated exactly twice in the entire file, both at **startup**
(`main.py:175`, `main.py:184`, inside `_load_historical_data()`, called once from
`start()`). There is no code path — grep confirms it — that appends the live tick's
own OHLC data (which the feed already decodes, see §6) back into `_df_cache`.

**What this means concretely:** a bot started at 09:15 and left running keeps
re-evaluating strategies against the exact same historical snapshot it fetched at
startup, all day. The live tick only ever touches `portfolio.update_price()` (P&L
marking) and the stop-loss check (`risk_manager.update_all`) — never the dataframe
strategies actually compute indicators from. A "live" signal generated at 14:00 is
scored on data that's current as of 09:15. This isn't a performance nuance; it makes
the live intraday loop functionally indistinguishable from replaying a stale
snapshot repeatedly, which is the opposite of what intraday trading needs.

**Why it wasn't obvious before this audit:** the bot *looks* live and reactive — it
does update prices in real time and does check stops on every tick — so the
staleness only shows up in what strategies are scored against, not in what the
dashboard displays.

---

## 2. The MarketPulse AI layer is hardcoded to daily bars

> ✅ **FIXED** (§7 item 5). `CompositeSignalEngine.score_symbol()`, `run_signal_engine()`,
> and `evaluate_alerts()` all take an explicit `timeframe` parameter now, defaulting to
> `"1d"` everywhere so nothing about the existing daily-cadence pages changed. A new
> `Signal.timeframe` column (migration `a89ec2781941`) keeps daily and intraday rows
> distinct — `latest_signal_per_stock(db, timeframe=...)` filters on it. Verified live:
> scored real 30-minute HDFCBANK/ICICIBANK signals without altering a single daily row
> the dashboard was already showing. 8 tests in `tests/test_signal_timeframe.py`.

Everything built across this session's phases — composite signal scoring, the
Signals page, Alerts, the "Why is it moving?" panel, Copilot, historical backfill —
shares one entry point, and it never varies its timeframe:

| Call site | Line | Timeframe |
|---|---|---|
| `scripts/run_signal_engine.py` | `:60` | `"1d"`, hardcoded |
| `scripts/backfill_historical_events.py` | `:74` | `"1d"`, hardcoded |
| `dashboard/backend/routers/portfolio_risk.py` | `:67` | `"1d"`, hardcoded |
| `dashboard/backend/routers/backtest.py` | Strategy Lab's default request | `"1d"` unless the user picks otherwise in the UI |

Contrast this with `main.py`, which reads `timeframes.primary` / `timeframes.intraday`
from config (`main.py:58-59`) and is architecturally timeframe-agnostic. The
MarketPulse layer doesn't have that parameter at all — `run_signal_engine()`,
`CompositeSignalEngine.score_symbol()`, and the alert evaluator have no timeframe
argument to change. Flipping `config/settings.yaml`'s `timeframes.primary` to `"15m"`
does nothing for any of this layer; it would need a code change, not a config change.

**Consequence:** the Signals page, Alerts, and Portfolio Risk correlation matrix all
reason about *yesterday's close vs. today's close*, not intraday price action. An
intraday trader watching the dashboard for entries is looking at a system that
updates once a session at best, evaluated every 5 minutes for no benefit (§5b).

---

## 3. Session-boundary blindness

> ✅ **FIXED** (§7 items 2 and 3). New `TechnicalIndicators.session_cumsum()` resets at
> each calendar-day boundary (falls back to a plain cumsum without a `DatetimeIndex`,
> so nothing else changes); `vwap()`, `vwap_bands()`, and
> `compute_anchored_vwap()` all use it now — 7 tests in `tests/test_session_vwap.py`,
> including one that reproduces the exact blend-across-days bug this section
> describes and confirms it's gone. `RangeBreakoutStrategy` is rewritten to anchor to
> today's actual 09:15 IST session open (falling back to the old bar-count window for
> non-NSE-shaped data — daily bars, crypto) — 8 tests in
> `tests/test_range_breakout.py`. The backtester now also simulates MIS
> auto-squareoff at 15:14 IST (new `utils.timeutils.is_mis_squareoff_time()`), so an
> intraday-product backtest can no longer hold a position across what would be a
> forced live close — 4 tests in `tests/test_backtester_mis_squareoff.py`.

Real intraday indicators must reset at the start of each trading session (09:15 IST)
— a VWAP computed across multiple days isn't a valid intraday reference level. Three
separate places in this codebase don't do that reset, one of them despite explicitly
documenting that it does:

**a. `AnchoredVWAPStrategy` doesn't actually anchor per session.**
`strategies/microstructure/anchored_vwap.py`'s docstring (lines 2-5) says: *"Unlike
cumulative VWAP (which has look-ahead bias), Anchored VWAP is reset at the start of
each trading session."* The actual implementation, `compute_anchored_vwap()`
(`anchored_vwap.py:33-53`), is:

```python
cum_vol  = volume.cumsum()
cum_tpv  = (tp * volume).cumsum()
vwap     = cum_tpv / cum_vol.replace(0, np.nan)
```

A plain `.cumsum()` over whatever `df` is passed in — no `groupby(df.index.date)`, no
session-start reset anywhere. It only produces correct output today because it
happens to always be called with single-session data; feed it multi-day intraday
bars (exactly what a real backtest or a fixed live cache would contain) and the VWAP
silently drifts across day boundaries, contradicting the function's own docstring.

**b. The shared `vwap()` utility has the identical issue.**
`feature_engine/indicators.py:28-31` — same unguarded `.cumsum()` pattern, used
wherever any strategy pulls VWAP from the shared indicator library.

**c. `range_breakout.py` (Opening Range Breakout) isn't NSE-session-aware at all.**
Its own docstring calls it an *"Asian session range breakout... first N hours"*
(`strategies/breakout/range_breakout.py:9-10`) with `range_bars` defaulting to `8`
(`:19`) — hour-scale, exchange-agnostic framing that reads like it was adapted from a
24-hour crypto/forex template, not NSE's actual convention (opening range = first
15-30 *minutes* after the 09:15 open, session ends 15:30). There's no
`09:15`/session-date logic in the file at all.

**d. The backtester has zero day-boundary awareness.**
`Backtester.run()` (`backtester/backtester.py`) iterates
`for i in range(self.warmup_bars, len(df))` — purely index-based. It never checks
whether bar `i` is the start of a new trading day, so it can't reset a session-anchored
indicator, and it never enforces the MIS auto-squareoff a live intraday position
would actually be subject to at 15:15 (§6b) — a backtested intraday strategy can hold
a position across a fictional "overnight," which live execution would never allow for
an MIS product. Backtest results for any of the intraday-styled strategies are not
representative of what would happen live, for this reason specifically (independent
of the general look-ahead-bias correctness the Phase 7 tests already verify).

---

## 4. Blocking I/O on the event loop

> ✅ **FIXED** (§7 item 4) for the paths reachable from the live tick loop. New
> `_post_async`/`_get_async`/`_put_async`/`_delete_async` wrappers run the existing
> synchronous calls via `loop.run_in_executor` instead of directly on the event loop
> thread; `_live_place`, `_poll_order_status`, `modify_order`, `cancel_order`,
> `place_basket_order`'s live branch, and `squareoff_all_mis`'s live branch all use
> them now. 6 tests in `tests/test_execution_nonblocking.py`, including one that
> proves the property that actually matters — another coroutine keeps making
> progress *during* a slow call, not just that both eventually finish.
> `UpstoxDataEngine`'s fetch calls were deliberately left synchronous: they're not on
> the live tick path today (only startup and synchronous dashboard/backtest
> contexts), so wrapping them wasn't warranted by this fix's actual risk.

`execution_engine/upstox_executor.py` places orders and polls their status with the
synchronous `requests` library, called directly (not via `loop.run_in_executor` or an
async HTTP client) from inside `async def` methods:

- `_live_place()` (`:242`): `resp = self._post("/order/place", payload)` — blocking.
- `_poll_order_status()` (`:256-272`): loops with `await asyncio.sleep(1)` between
  iterations (so it's not a busy-loop — that part's fine), but each iteration's
  `self._get(...)` call (`:262`) is still a blocking synchronous request with a
  15-second timeout (`upstox_executor.py:166`).

Since `main.py` runs everything — the WebSocket tick stream, order placement, and
status polling — on one asyncio event loop, a blocking call anywhere on that loop
stalls processing for *every other symbol* until it returns. Placing one order or
polling its status delays the stop-loss check and price update for every other open
position for that call's duration. `UpstoxDataEngine`'s historical fetches
(`data_engine/upstox/upstox_data.py`) have the same pattern. For daily-bar swing
trading this is invisible (nothing needs sub-second reaction time); for intraday,
with multiple concurrent positions, it's a real correctness-adjacent risk gap — a
stop-loss on position B can be delayed by however long an order for position A takes
to round-trip.

---

## 5. Data/infra limits

> **§5a is an external constraint, not fixed (can't be — it's Upstox's API, not this
> codebase).** New finding from live-verifying the §2/§7 fix: on this account, Upstox's
> v2 historical-candle endpoint returns **HTTP 400 for the 5-minute and 15-minute
> intervals specifically** — 30-minute and 60-minute work fine. This matches the
> "broken Upstox 15-minute interval" note already in `backfill_historical_events.py`.
> The new intraday scheduler track (§7 item 6) defaults to `"30m"` for exactly this
> reason, with the caveat documented in `config/settings.yaml`. §5b and §5c are fixed
> — see below.

**a. Upstox intraday historical caps are tighter than daily.** From
`upstox_data.py`'s `_MAX_LOOKBACK_DAYS`: 1-10 minute bars cap at 100 days, 15-60
minute bars at 200 days, vs. 2000 days for daily/weekly/monthly. Not a bug, just a
real constraint on how much intraday backtest history is obtainable per request —
worth knowing before assuming a multi-year intraday backtest is possible.

**b. The scheduler's cadence doesn't match intraday's needs.** ✅ **FIXED.** A separate
opt-in intraday track (`scheduler.intraday_*` in `config/settings.yaml`, disabled by
default) runs `intraday_signal_engine`/`intraday_alert_evaluation` on their own
interval (default 15 min — reasonable given `UpstoxDataEngine` caches intraday
fetches for ~1h, so most runs hit cache, not the API), coexisting with the unchanged
daily jobs. 6 tests in `tests/test_intraday_scheduler.py`.

**c. No tick→candle aggregator exists, despite the raw material being available.**
✅ **FIXED** — this is the same fix as §1: `data_engine/live_bars.py`'s
`LiveBarAggregator` is that aggregator, consuming exactly the `to_candle_event()`
data this section describes.

---

## 6. What actually already works

Worth stating plainly, since some of this contradicts `docs/known_issues.md` (dated
2026-05-27, written before this session's work and evidently not updated since):

**a. WebSocket auto-reconnect with exponential backoff exists and looks correct.**
`known_issues.md` claims *"Auto-reconnect on WebSocket drop: Not implemented."* That's
stale — `data_engine/upstox/upstox_feed.py:109-133` has `_reconnect_delay`, doubling
backoff up to `_RECONNECT_MAX`, reset on successful reconnect. This should be removed
from that doc's limitations list.

**b. MIS auto-squareoff is real, not just a config value.** `main.py:209-213` checks
`should_squareoff_mis()` (`utils/timeutils.py:30-36`, fires once the clock passes
15:14 IST) on every tick and calls `executor.squareoff_all_mis()`. The mechanism
exists and is wired into the live loop — it's the backtester (§3d) that doesn't
simulate it, not that it's missing from execution.

**c. The execution layer is genuinely intraday-aware.** `risk_manager.py`'s
`FO_LOT_SIZES` and `snap_to_lot()`, `UpstoxProduct` (MIS vs CNC), and per-product
commission rates in config (`execution.commission_intraday` vs `commission_delivery`)
are all real and used, not placeholders.

**d. The Chart page already renders intraday candles.** Frontend interval selector
goes down to 1 minute (`dashboard/frontend/src/pages/Chart.tsx`), correctly capped by
the API's own max-lookback-per-interval — this is a *display* capability, separate
from the *decision-making* gaps above, but it means the UI groundwork for showing
intraday data isn't missing, only the intelligence layer feeding it is.

**e. 13 of the enabled strategies are intraday-styled in intent** (VWAP reversion,
anchored VWAP, cumulative delta, volume profile, gift Nifty gap, range breakout) and
are already `timeframes.intraday`-selectable in config. Whether they're *correctly*
intraday (§3) is the caveat — the intent and the config knob are there.

---

## 7. Fix roadmap, prioritized

> ✅ **All six items below are done.** Executed in this order; each item's tests are
> cited in its section above.

**P0 — without these, nothing else here matters:**

1. **Wire live candle events into `_df_cache`.** Make `UpstoxFeed`'s
   `to_candle_event()` output update/append to the strategy dataframe on each closed
   candle (not raw tick — aggregate to the configured `intraday_tf` first), so
   `generate_signals()` scores against current-session data instead of a startup
   snapshot. This alone is the highest-leverage fix in this whole document — it's
   what makes the live loop actually live.
2. **Fix session-boundary handling in VWAP and ORB.** Add a `groupby` on session
   date (or an explicit reset trigger at 09:15) to `vwap()` and
   `compute_anchored_vwap()`; rewrite `range_breakout.py`'s range window to NSE's
   actual first-15/30-minutes convention instead of the current hour-count default.

**P1 — needed before intraday backtest/live results can be trusted relative to each
other:**

3. **Make the backtester session-aware.** Detect day boundaries while iterating bars;
   reset session-anchored indicators there; simulate MIS auto-squareoff at 15:15 for
   any product-typed-as-intraday backtest so results reflect what live execution
   would actually allow.
4. **Move blocking HTTP off the event loop.** Wrap `execution_engine`'s and
   `UpstoxDataEngine`'s `requests` calls in `loop.run_in_executor(None, ...)`, or
   migrate to `httpx.AsyncClient` (already a project dependency per
   `requirements.txt`) for the hot paths — order placement and status polling first.

**P2 — extends intraday support to the MarketPulse AI layer:**

5. **Give the composite signal engine a timeframe parameter.** Thread it through
   `CompositeSignalEngine.score_symbol()`, `run_signal_engine()`, and the alert
   evaluator so they can run against `15m`/`5m` bars, not just `"1d"`.
6. **Retune the scheduler for intraday cadence**, gated separately from the existing
   daily-bar jobs so both can coexist — an intraday job needs to run near the bar
   size (minutes, not 5-minute-against-daily-data), with real attention to Upstox's
   intraday rate/lookback caps (§5a) if scanning the full universe.

None of these are config toggles — items 1 and 3 in particular are real engineering
(a live bar aggregator, a backtester session model), not parameter tuning.

---

## 8. Bottom line

The daily-bar / swing-trading design of the MarketPulse AI layer (§2) was a legitimate
choice, not a bug — it simply wasn't what intraday trading needed, and now runs
alongside a real intraday track instead of being replaced by one. The more serious
finding was §1: even the part of the codebase that predates this session and looked
purpose-built for live intraday trading had a silent staleness bug that meant the
"live" strategy loop wasn't actually reacting to the live session. That's fixed, along
with every other item this audit found — a live bar aggregator
(`data_engine/live_bars.py`), session-aware indicators, a session-aware backtester,
non-blocking order execution, timeframe-aware signals/alerts, and an opt-in intraday
scheduler track. 55 new tests across `tests/test_live_bars.py`,
`tests/test_bot_live_refresh.py`, `tests/test_session_vwap.py`,
`tests/test_range_breakout.py`, `tests/test_backtester_mis_squareoff.py`,
`tests/test_execution_nonblocking.py`, `tests/test_signal_timeframe.py`, and
`tests/test_intraday_scheduler.py`, plus a live end-to-end verification against real
Postgres/Upstox data that confirmed the fix without disturbing a single existing daily
signal row.

One thing this fix *didn't* and can't touch: Upstox's own API rejects the 5-minute and
15-minute intervals on this account (§5), which is why the intraday scheduler and the
live bot's own `timeframes.intraday` default differ — worth reconciling once you know
which interval your account actually has access to.
