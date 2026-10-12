# Market Intelligence Sources

Beyond candles, several strategies and features use market-wide data: India
VIX, institutional flows, delivery volumes, the F&O ban list, GIFT Nifty, the
order book and option-implied volatility. This chapter lists each source, where
it comes from and how fresh it is.

All NSE sources scrape `nseindia.com`'s public JSON endpoints, which need a
browser-like `User-Agent` and a cookie from a first visit to the home page —
the code does both. NSE rate-limits and sometimes blocks scrapers, so every
source caches its results and falls back to the last cached copy when a
request fails.

## India VIX

`data_engine/upstox/india_vix.py`. India VIX is NSE's 30-day implied
volatility index, computed from Nifty options.

| Function | Purpose |
|---|---|
| `get_current_vix(engine)` | Upstox LTP of `NSE_INDEX\|India VIX`, else the last cached close |
| `fetch_vix_history_nse(days)` | Historical closes from NSE archives (cached in `data/nse_cache/`) |
| `classify_vix(level)` | Regime label (below) |
| `vix_percentile(level, 252)` | Where today's VIX sits in the past year, 0–100 |
| `vix_spike_today(threshold)` | VIX up more than the threshold % since yesterday's close |

| VIX level | Regime |
|---|---|
| ≥ 25 | `EXTREME_FEAR` — panic; reversals likely |
| 20–25 | `HIGH_FEAR` |
| 15–20 | `ELEVATED` |
| 12–15 | `NORMAL` |
| 10–12 | `LOW` |
| < 10 | `EXTREME_COMPLACENCY` — tail risk building |

Used by the [VIX strategy](strategies-macro.md#india-vix-strategy) and the
advanced feature set.

## FII / DII flows

`data_engine/nse_data.py`:

- `fetch_fii_dii_activity(days)` — daily net cash-market buying/selling by
  Foreign and Domestic Institutional Investors in ₹ crore, from
  `/api/fiidiiTradeReact`. Cached per day in
  `data/nse_cache/fii_dii_<date>.parquet`. NSE publishes around 17:30 IST.
- `get_fii_sentiment(lookback_days=5)` — sums FII net over the window:
  above +₹1,000 Cr → `BULLISH`, below −₹1,000 Cr → `BEARISH`, otherwise
  `NEUTRAL`; also returns DII net, combined net and the daily average.

Used by the [FII/DII strategy](strategies-macro.md#fiidii-flow).

## Delivery volumes

- `fetch_delivery_data(date)` — NSE's full bhav copy
  (`sec_bhavdata_full_<DDMMYYYY>.csv`) with traded and delivered quantity per
  stock; cached per date.
- `get_delivery_pct(symbol, date)` — share of traded volume actually taken
  into delivery. High delivery % on a rising price suggests genuine
  accumulation rather than intraday churn.
- `get_high_delivery_stocks(threshold)` — every stock at or above the
  threshold.

## F&O ban list

`fetch_fo_ban_list()` / `is_in_fo_ban(symbol)` — stocks whose open interest
exceeds 95 % of the market-wide limit; no new F&O positions may be opened in
them that day. From `/api/fo-secban`, cached daily.

## Corporate actions calendar

`fetch_corporate_actions(days_ahead)` / `has_upcoming_corporate_action(symbol,
days)` — upcoming dividends, splits, bonuses and rights. This is the
forward-looking calendar; the historical price adjustment uses a separate
module, described in [Market Data](market-data.md#split-and-bonus-adjustment).

## GIFT Nifty

`data_engine/gift_nifty.py`. GIFT Nifty trades in GIFT City from 06:30 IST
and is the usual guide to where Nifty will open. `get_gift_nifty()` computes
the gap against Nifty's previous close and classifies it:

| Gap | Class |
|---|---|
| ≥ +1.5 % | `STRONG_BULLISH` |
| +0.5 to +1.5 % | `WEAK_BULLISH` |
| −0.5 to +0.5 % | `NEUTRAL` |
| −1.5 to −0.5 % | `WEAK_BEARISH` |
| ≤ −1.5 % | `STRONG_BEARISH` |

> **Limitation:** there is no working GIFT Nifty price source. The code tries
> the Upstox key `NSE_INDEX|GIFT NIFTY`, which does not exist in the Upstox
> instrument master, and then falls back to NSE's *Nifty 50* last price — which
> before 09:15 is simply yesterday's close. The computed gap is therefore near
> zero and the classification `NEUTRAL` almost every morning. See
> [Project Status](../appendix/status.md).

## Order book

`data_engine/orderbook.py`. `OrderBookSnapshot` wraps bid/ask levels and
derives best bid/ask, mid price, spread (absolute and %), **imbalance**
`(bid volume − ask volume) ÷ (bid volume + ask volume)` from −1 to +1, and
**whale pressure** — the net direction of unusually large orders in the top
five levels. `OrderBookTracker` holds the latest snapshot per symbol for
subscribers. Snapshots can be built from `UpstoxDataEngine.get_market_depth()`.

## Option-implied volatility

`data_engine/upstox/iv_surface.py`. `build_iv_surface(underlying, spot,
option_chain)` turns an Upstox option chain (`get_option_chain()`) into an
`IVSurface` with, per expiry, the volatility smile, ATM IV, 25-delta risk
reversal (skew) and butterfly, and across expiries:

| Method | Meaning |
|---|---|
| `atm_iv()` | ATM implied volatility of the nearest expiry |
| `term_structure()` | `[(days to expiry, ATM IV)]` |
| `iv_rank_current()`, `iv_percentile_current()` | Where current IV sits in its history |
| `is_high_iv()` / `is_low_iv()` | Rank above/below thresholds — favour selling / buying options |
| `pcr()` | Put/call open-interest ratio |
| `max_pain()` | Strike where option writers lose least at expiry |
| `summary()` | All of the above as a dict |

The risk-free rate is 6.5 % and a year has 252 trading days. Used by the
options strategies (not yet wired into the engine) and
`scripts/option_chain.py`.
