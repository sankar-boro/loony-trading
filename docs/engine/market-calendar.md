# Market Hours and Calendar

The engine needs to know when NSE is open, when intraday positions must be
closed and which days are holidays. Two modules provide this:
`data_engine/upstox/market_hours.py` (calendar-aware) and `utils/timeutils.py`
(session helpers used by the scripts and the bot).

## The NSE day

| Time (IST) | Event |
|---|---|
| 09:00–09:15 | Pre-open order matching (`is_pre_open()`) |
| **09:15** | Equity session opens |
| **15:14** | The bot's MIS squareoff — six minutes before the broker's |
| 15:20 | Upstox force-closes remaining MIS positions at market |
| **15:30** | Session closes |
| 15:35 | The paper trader writes its end-of-day report |
| from 17:00 | After-market order window (`is_amo_window()`) |
| 03:30 next day | Upstox daily access tokens expire |

Saturdays, Sundays and NSE trading holidays are closed.

## Holidays

`is_holiday(date)` checks a set of dates loaded once per process:

1. **Cache** — `data/nse_holidays.json`, used if fetched within the last 30
   days.
2. **NSE API** — `https://www.nseindia.com/api/holiday-master?type=trading`
   (capital-market segment); the result is written to the cache.
3. **Offline fallback** — if NSE is unreachable and there is no fresh cache: a
   built-in 2025 list plus every date in `india_market.holidays` in
   `config/settings.yaml`.

Keep `india_market.holidays` current each year (the 2026 dates are already
there) so the bot still knows the holidays when NSE's API is down. To refresh
early, delete `data/nse_holidays.json`.

## Functions

| Function | Module | Returns |
|---|---|---|
| `is_market_open(dt=None)` | market_hours | Weekday, not a holiday, 09:15–15:30 |
| `is_holiday(d)` | market_hours | NSE trading holiday |
| `is_pre_open()`, `is_amo_window()` | market_hours | Pre-open / after-market windows |
| `minutes_to_close()`, `next_market_open()` | market_hours | Used by the dashboard status bar |
| `now_ist()`, `now_utc()` | timeutils | Current time |
| `is_market_session()` | timeutils | Same as `is_market_open()` for now |
| `next_market_open()` | timeutils | Next 09:15 IST, skipping weekends and holidays |
| `minutes_to_market_open()`, `minutes_to_market_close()` | timeutils | Countdowns |
| `should_squareoff_mis()` | timeutils | Now is 15:14 IST or later |
| `is_mis_squareoff_time(ts)` | timeutils | Same test for any timestamp — used by the backtester |
| `minutes_to_squareoff()` | timeutils | Minutes until 15:14 |

## Who uses what

| Component | Behaviour outside market hours |
|---|---|
| `main.py` | Paper mode: one pass of the strategies over cached history, then exits. Live mode: connects the feed and waits |
| `paper_trade.py` | Sleeps until the next open (checking at least hourly) |
| `live_signals.py` | Prints the next open; `--refresh` waits |
| `market_watch.py` | Shows pre-open / post-close status |
| Scheduler | Signal and alert jobs skip their run (`market_hours_only`) |
| Dashboard | Status bar shows the next open |

## Circuit breakers

`data_engine/circuit_detector.py` (`CircuitBreakerDetector`) implements SEBI's
rules: market-wide halts at ±10 %, ±15 % and ±20 % index moves (halt length
depends on the time of day) and stock price bands (±10 % by default, with a
warning 0.5 % before the band). It can compute a stock's limits from the
previous close, report whether it is circuited or near it, scan a portfolio,
and fetch NSE's daily price-band list.

The bot does not consult it yet — it is available as a library for
strategies and scripts. See [Project Status](../appendix/status.md).
