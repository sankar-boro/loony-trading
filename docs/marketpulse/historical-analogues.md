# Historical Analogues

"When news like this happened before, what did the stock do next?" The
analogue engine answers that from realised past outcomes stored in the
`historical_events` table. It is analysis of the past, never a forecast — every
place it is shown carries the label *"Historical analysis of past events — not a
prediction"*.

## Querying analogues

`signals.historical.find_analogues(db, event_type, direction=None, regime=None,
stock_id=None, limit=500)` loads the most recent matching events and reports,
for each horizon:

| Field | Meaning |
|---|---|
| `horizon` | `15m`, `1h`, `1d`, `5d` |
| `sample_count` | Events with a known price at that horizon |
| `win_rate_pct` | % of those where the price was higher than before the event |
| `median_return_pct` | Median % return |

Horizons with no data are reported with zero samples rather than omitted, so
"no edge" and "no data" are distinguishable. In practice only `1d` and `5d`
have data: the project works from daily bars.

API: `GET /api/historical-analogues?event_type=earnings&direction=bullish&symbol=TCS`.

Analogues feed three places: the composite score's **Historical** component
(1-day win rate with ≥ 5 samples), the **Why is it moving?** panel, and the
**Copilot**.

## Building the history

`scripts/backfill_historical_events.py` has two modes.

### Organic backfill (the real data)

```bash
python scripts/backfill_historical_events.py                 # events older than 7 days
python scripts/backfill_historical_events.py --min-age-days 10
```

For every stock–news link (`stock_events`) older than `--min-age-days` that has
not been backfilled yet, it:

1. Fetches daily candles around the event.
2. Takes the close of the last bar at or before the event as `price_before` —
   only data that existed at the time, so no look-ahead.
3. Records the closes 1 and 5 trading days later, when they exist.
4. Detects the market regime from the bars before the event.
5. Stores a `historical_events` row with the event type, direction, regime and
   prices.

The scheduler runs this daily at 18:00 IST, so the analogue database grows on
its own as the news pipeline runs.

### Demo seed

```bash
python scripts/backfill_historical_events.py --seed-demo earnings --seed-count 40 --seed-symbol RELIANCE
```

Generates synthetic events with a fixed random seed (reproducible), cycling
bullish/bearish/neutral with drifts of +1.2 %, −1.0 % and 0 % per day plus
noise. Every row's description starts with `[DEMO]`. Use it to try the
analogue features before real history has accumulated; do not mix it with real
data you intend to rely on.

## Interpreting results

- Fewer than about 20 samples tells you very little — a 70 % win rate on 7
  events is easily luck.
- Events of the same type differ in size: a small earnings beat and a huge one
  are both `earnings`. Direction and regime filters help.
- A high win rate with a near-zero median return means small, frequent gains —
  often not worth the trading costs.
