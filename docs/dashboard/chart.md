# Chart

The Chart page (`/chart`, `pages/Chart.tsx`) is a TradingView-style candlestick
chart for any stock or index in the universe, with a live price list and the
"Why is it moving?" explanation panel.

## Opening a symbol

- From the **Home** page, click any stock in the universe panel — it opens
  here with that symbol.
- Use the symbol dropdown in the top bar (grouped into **Indices** and one
  group per sector), or click a row in the right-hand list.
- With no symbol passed in, the page opens on **NIFTY50**.

## Intervals and ranges

The top bar has interval buttons and range buttons. Upstox limits how much
intraday history one request can return, so the page caps the range per
interval:

| Button | Interval sent | Upstox candles used | Max days |
|---|---|---|---|
| 1m | `1minute` | 1-minute | 3 |
| 5m | `5minute` | 1-minute, resampled to 5 | 5 |
| 15m | `15minute` | 1-minute, resampled to 15 | 7–10 |
| 30m | `30minute` | 30-minute | 30 |
| 1H | `60minute` | 30-minute, resampled to 60 | 30 |
| 1D | `day` | daily | 730 |
| 1W | `day` (two-year range) | daily | 730 |

Ranges: **5D, 1M, 3M, 6M, 1Y, 5Y**. The effective range is the smaller of the
chosen range and the interval's maximum, so "5Y" on daily bars shows the
two-year API maximum.

The 5m, 15m and 1H views are built in the backend by resampling finer candles
(`pandas.resample`, left-labelled, left-closed), because those Upstox
intervals are unreliable on some accounts (see
[Market Data](../engine/market-data.md)).

Data comes from `GET /api/chart/{symbol}?interval=…&days=…`:

```json
{ "symbol": "RELIANCE", "interval": "day",
  "candles": [ { "time": 1759190400, "open": 2930.0, "high": 2961.5,
                 "low": 2921.1, "close": 2950.4, "volume": 4120332 }, … ] }
```

`time` is a Unix timestamp in seconds. The endpoint returns **401** without a
valid Upstox token, so the chart is empty in demo mode.

## Reading the chart

- **Candles** with a **volume histogram** beneath, drawn with TradingView's
  `lightweight-charts`.
- The header shows the latest bar's **O/H/L**, volume, and the change versus
  the previous bar in ₹ and %.
- The crosshair follows the mouse; scroll to zoom and drag to pan.
- The bottom bar shows how many bars are loaded and the interval.
- The left toolbar (cursor, trend line, horizontal line, rectangle, circle,
  text, Fibonacci) is **visual only** — drawing tools are not implemented yet.

## Price list

The right-hand **MyStocks** list shows indices first and then every universe
stock by sector, with last price and change from the `GET /api/stream/prices`
stream (the 30 watchlist stocks and three indices are streamed; others show
"—"). Type in the search box to filter by symbol or company; click to switch
the chart.

## Why is it moving?

The collapsible panel below the chart calls `GET /api/stocks/{symbol}/why` when
you open it. It explains the stock's recent behaviour from evidence in the
MarketPulse database, and says so when there is not enough:

| Section | Content |
|---|---|
| Signal | Latest composite signal: direction (bullish/bearish/watch/no signal), score and confidence |
| Conclusion | One sentence naming the biggest driver, plus the historical win rate when there are at least 5 comparable events |
| Drivers | The top four score components, ranked by contribution = component score × weight |
| Historical Analogue | How often similar past news events (same type and direction) closed higher the next day, and the median return |
| Recent News | Up to five headlines from the last 7 days, linked to the source |

This needs the database and a scored signal for the stock. How each piece is
computed is explained in [Why and the Copilot](../marketpulse/why-and-copilot.md).
