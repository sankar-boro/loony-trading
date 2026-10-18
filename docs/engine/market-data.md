# Market Data

Everything the engine knows about prices comes through
`data_engine/upstox/upstox_data.py` (`UpstoxDataEngine`), which resolves
symbols with the instrument registry, downloads candles, adjusts them for
splits and bonuses, caches them, and falls back to demo data when there is
no token.

## The stock universe

`config/instruments.py` is the single source of truth for what the project
trades: 91 NSE stocks in 18 sectors (`STOCK_UNIVERSE`) plus the indices
(`INDEX_INSTRUMENTS`: Nifty 50, Bank, IT, Fin Service, Auto, FMCG, Midcap
50/150/Select, India VIX, Sensex and GIFT Nifty, some under two aliases). Each stock has:

| Field | Example |
|---|---|
| `isin` | `INE002A01018` — forms the Upstox key `NSE_EQ\|INE002A01018` |
| `name`, `sector`, `industry` | Reliance Industries, Energy, Oil & Gas |
| `market_cap` | Large Cap / Mid Cap / Small Cap |
| `fno`, `nifty50`, `nifty_next` | F&O eligible, index memberships |

`INSTRUMENTS` maps every symbol and index alias (`NIFTY50`, `BANKNIFTY`,
`NIFTYIT`, `MIDCAP`, …) to its Upstox instrument key.

**Never hardcode a key.** Code looks keys up here (`INSTRUMENTS["TCS"]`,
`INDEX_INSTRUMENTS["VIXINDIA"]`, `STOCK_UNIVERSE["TCS"]["isin"]`) rather than
keeping its own copy of an ISIN or an `NSE_INDEX|…` string.
`tests/test_instrument_isins.py` scans every non-test Python file and fails
on any such literal outside `config/instruments.py`. Docstrings and comments
may still show example keys. To add a stock or index, add it here and
everything that looks it up picks it up. Helpers:
`get_sector_map()`, `get_fno_symbols()`, `get_nifty50_symbols()`,
`get_symbols_by_sector()`, `get_large_cap_symbols()`, `symbol_info()`.

**ISINs change.** After a split or bonus a company often gets a new ISIN and
the old key returns no data — in October 2026 ten universe stocks had gone
stale this way. `tests/test_instrument_isins.py` checks every ISIN against the
downloaded Upstox master (`data/instruments/NSE.csv`, from
`bash scripts/fetch_instruments.sh`); run it after refreshing the master and
update `config/instruments.py` when it fails. Because nothing else holds a
copy, that one edit fixes every script, the bot and the dashboard.

## The instrument registry

`InstrumentRegistry` (`data_engine/upstox/instruments.py`) maps trading
symbols to instrument keys and holds per-contract metadata (lot size, tick
size, expiry, strike) for equities, F&O and indices.

- `load(exchanges)` downloads each exchange's master from
  `https://assets.upstox.com/market-quote/instruments/exchange/{NSE,BSE,MCX}.csv.gz`
  (one file per exchange, filtered by segment: `NSE_EQ`, `NSE_FO`,
  `NSE_INDEX`, …) and caches each segment as `data/instruments/<SEGMENT>.json`
  for 18 hours.
- It then **seeds every symbol from `config/instruments.py`**, overriding the
  master: the project's own symbols always resolve, even offline, and an
  unrelated master instrument with the same ticker (the master has an ETF
  called `MIDCAP`) can never shadow the universe.
- `get_key(symbol)`, `get_metadata(key)`, `get_lot_size(key)`,
  `get_tick_size(key)`, `round_to_tick(price, key)`, `search(query)`,
  `nifty50_keys()`, `fo_instruments(underlying)`.

Real F&O keys are numeric exchange tokens (`NSE_FO|48906`), so contract
details such as the lot size come only from the master.

## Fetching candles

```python
from data_engine.upstox import UpstoxAuth, InstrumentRegistry, UpstoxDataEngine

auth = UpstoxAuth(api_key, api_secret, redirect_uri); auth.load_token()
registry = InstrumentRegistry(); registry.load()
engine = UpstoxDataEngine(auth, registry)

df = engine.fetch_ohlcv("RELIANCE", timeframe="1d", lookback_days=365)
# DataFrame[open, high, low, close, volume], indexed by UTC timestamp
```

`symbol` may be a universe symbol, an index alias or a raw instrument key.

### Timeframes and lookback limits

| Internal timeframe | Upstox interval | Max lookback (days) |
|---|---|---|
| `1m`, `3m`, `5m`, `10m` | 1/3/5/10 minute | 100 |
| `15m`, `30m` | 15/30 minute | 200 |
| `1h` | 30 minute, resampled to 1 hour | 200 |
| `60m`, `2h` | 60/120 minute (`60m` is also resampled to 1 hour) | 200 |
| `4h` | 240 minute | 400 |
| `1d`, `1w`, `1M` | day / week / month | 2000 |

Requests beyond the limit are silently shortened. Minute intervals are fetched
in 30-day chunks.

> **Account limitation:** on the account this project was built against, the
> historical-candle endpoint returns **HTTP 400 for 5-minute and 15-minute
> intervals**, while 30-minute and 60-minute work. The intraday tools therefore
> default to 30 minutes. Check yours with `python scripts/test_upstox.py`.

### Caching

Each result is written to `data/cache/upstox_<symbol>_<timeframe>.parquet` and
reused while it is younger than **1 hour for minute bars** and **12 hours for
daily and longer bars**, and only if it reaches back far enough for the
request. A fresh 60-day file is not returned for a three-year request; it is
refetched. A longer file is trimmed to the requested range. Delete the files
to force a refresh.

### Split and bonus adjustment

Upstox returns unadjusted history: a 1:1 bonus halves the price overnight and
would look like a 50 % crash to every strategy. For equities (not indices),
`fetch_ohlcv` multiplies all bars before each ex-date by an adjustment factor
(`data_engine/upstox/corporate_actions.py`):

| Action | Example | Factor applied to earlier bars |
|---|---|---|
| Bonus a:b | 1:1 | b ÷ (a + b) = 0.5 |
| Split / sub-division | 1:10 | smaller ÷ larger = 0.1 |
| Rights | ratio in text | treated like a split ratio (approximate) |

Actions come from NSE's public corporate-actions API (three years back),
cached in `data/corporate_actions.json` for 24 hours; if NSE is unreachable a
stale cache is used. Dividends are not adjusted. Pass `adjust_prices=False` to
the engine to disable adjustment.

### Demo mode

With no access token, `fetch_ohlcv` returns synthetic daily bars from
`data_engine/demo_ohlcv.py` instead of calling Upstox, and logs
`DEMO DATA: no Upstox token`. The series is a deterministic random walk seeded
from the symbol name, anchored near a realistic price for well-known stocks
and a market-cap-tier range for others. Bars are always daily, whatever
timeframe was requested.

## Quotes, depth and option chains

| Method | Upstox endpoint | Returns |
|---|---|---|
| `get_ltp(symbols)` | `/market-quote/ltp` | `{symbol: last price}` |
| `get_quotes(symbols)` | `/market-quote/quotes` | LTP, OHLC, volume, net change |
| `get_market_depth(symbol)` | `/market-quote/depth` | 5-level bid/ask |
| `fetch_intraday(symbol, interval)` | `/historical-candle/intraday/…` | Today's candles |
| `get_option_chain(underlying, expiry)` | `/option/chain` | Per strike: call/put LTP, OI, IV, volume |
| `get_expiry_dates(underlying)` | `/option/contract` | Available expiries |
| `start_polling(symbols, interval_sec)` | quotes every N s | Candle-shaped events to `subscribe()`d callbacks — a fallback when the WebSocket is unavailable |

A 401 from Upstox raises `PermissionError("Upstox token invalid or expired")`;
other errors are logged and return empty results.

## Crypto (secondary)

`data_engine/market_data.py` (`MarketDataEngine`) offers the same
`fetch_ohlcv`/`subscribe` surface over any ccxt exchange (Binance by default).
`main.py --mode backtest --market crypto` and the dormant `CryptoBotAddon` use
it; the Indian-market bot does not.
