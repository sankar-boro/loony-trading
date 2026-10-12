# The Live Feed

During market hours the bot in `main.py` gets prices from Upstox's WebSocket
market-data feed, turns ticks into one-minute bars, and splices those bars onto
its historical data so strategies always score against the current session.

## UpstoxFeed

`data_engine/upstox/upstox_feed.py`:

```python
feed = UpstoxFeed(auth, registry, mode="full")
feed.subscribe(on_tick)                    # sync or async callback
await feed.start(["RELIANCE", "TCS", "NIFTY50"])   # runs until stop()
```

| Mode | Contents |
|---|---|
| `ltpc` | Last price, close, change — lowest bandwidth |
| `full` | Full quote incl. OHLC and depth (what the bot uses) |
| `option` | Full quote plus option Greeks |

What it does:

1. Resolves symbols to instrument keys through the registry and remembers
   which symbol each key was subscribed for.
2. Connects to `wss://api.upstox.com/v2/feed/market-data-feed` with the access
   token (30 s ping interval) and sends a subscription message.
3. Decodes each binary message with the protobuf definitions from
   `upstox-python-sdk`; if the SDK is missing, a lightweight manual parser
   extracts last prices only (a warning is logged at startup).
4. Labels every tick with **the symbol it was subscribed under**
   (`RELIANCE`, `NIFTY50`) — not the raw key or the master's own name — so it
   matches how the bot keys positions and data.
5. Drops ticks with no price (≤ 0). Large jumps are filtered later by the bot
   (see below).
6. Calls every subscriber with a candle-shaped event:

```python
{"symbol": "RELIANCE", "timeframe": "tick", "ts": 1791545520123,   # ms
 "open": …, "high": …, "low": …, "close": <last price>, "volume": …}
```

In `full` mode the open/high/low/volume come from Upstox's running one-minute
candle (interval `I1`), so each tick carries the current minute's OHLCV.

**Reconnection**: any disconnect or error is logged and retried after 2 s,
doubling up to 60 s; a successful connection resets the delay.
`add_symbols()` subscribes more instruments on a live connection.

## Tick sanity check

`UpstoxTradingBot._is_sane_tick()` rejects corrupt prices before stops or
strategies see them:

- price ≤ 0 → dropped;
- a move larger than `execution.max_tick_jump_pct` (default 0.20 — the widest
  NSE circuit band) from the last accepted price → dropped and logged;
- if the next ticks agree on the new level (three in a row within 1 % of each
  other), it is real — for example a split re-basing the feed — and accepted.

## LiveBarAggregator

`data_engine/live_bars.py` builds bars from the tick events:

- `update(event)` tracks the forming one-minute bar per symbol and returns
  `True` exactly when a bar has closed — which is known only when the first
  tick of the next minute arrives, so no bar is ever revised afterwards.
- `get_bars(symbol, timeframe)` returns closed bars resampled to `5m`, `15m`,
  `30m`, `1h`, …, by wall-clock flooring. NSE's 09:15 open falls on every
  common bucket boundary, so buckets line up with the session. The forming bar
  is excluded unless `include_forming=True` — scoring a half-built candle would
  be inconsistent.
- Up to 500 one-minute bars are kept per symbol (more than one session).
- `clear()` resets everything; the bot calls it at startup so a previous run's
  bars never leak in.

`merge_live_onto_history(base, live)` appends the live bars to the historical
frame, dropping any historical rows at or after the first live bar.

## How the bot uses it

At startup the bot fetches `timeframes.primary` history for every symbol and
`timeframes.intraday` history (60 days) for every equity symbol. Then, on each
tick:

1. Sanity-check the price; record it as the symbol's last price.
2. Run the MIS squareoff if past 15:14 IST (once per day).
3. Check stops and targets on every open position in that symbol.
4. Feed the tick to the aggregator. When a bar closes and a full
   `timeframes.intraday` bucket has completed, rebuild the symbol's intraday
   frame from history + live bars and re-score the strategies on it.
5. Symbols without an intraday base (indices) are scored against the daily
   frame instead.

The full loop, including entries and position handling, is in
[Architecture of the Bot](architecture.md).
