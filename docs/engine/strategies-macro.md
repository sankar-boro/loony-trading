# Macro Strategies: VIX, GIFT Nifty, FII/DII

Three strategies trade the whole market from market-wide data rather than a
stock's own chart. All three **only produce signals for index symbols** — a
symbol containing `NIFTY` or `BANKNIFTY` (`NIFTY50`, `BANKNIFTY`, `NIFTYIT`, …)
— and return nothing for stocks.

Two caveats apply to all three:

- **They read today's data, not the bar's.** VIX history, FII flows and the
  GIFT gap are fetched as of *now*, whatever bar is being evaluated. Their
  results in a backtest therefore do not reflect what they would have done on
  those historical days.
- **Index signals are research-only.** An index cannot be bought or sold; a
  BUY on `NIFTY50` would have to become a futures, options or ETF trade, and
  F&O contracts cannot be resolved yet. So a signal on an index never becomes
  an order. The executor refuses it in live and paper mode
  (`risk_manager.is_index`), and the bot logs a `block` event: "an index is
  not tradable itself". The signals still appear in the composite scores and
  the bot's events. Before 2026-10-19, paper mode traded the index as if it
  were a share. Backtests on an index still simulate it as a tradable price,
  as a rough stand-in for futures.

## India VIX Strategy

`vix_strategy` · `strategies/volatility/vix_strategy.py` · regime: all

Loads recent India VIX closes ([Market Intelligence](market-intelligence.md#india-vix))
and evaluates three sub-strategies, returning the most confident:

| Sub-strategy | Condition | Signal | Confidence |
|---|---|---|---|
| **Spike reversal** | VIX ≥ `vix_spike_entry`, up at least half of `spike_threshold_pct` vs its 5-day average, and the index down more than `nifty_drop_pct` over 5 days | BUY — fear peaks tend to precede bounces | 0.60 + (VIX percentile − 70) ÷ 100 + size of the 5-day fall ÷ 20, max 0.90 |
| **Low-VIX hedge** | VIX ≤ `vix_low_entry` on at least 70 % of `consecutive_low_days` recent days | SELL — complacency precedes corrections (intended as buying puts) | 0.55 + (entry − VIX) ÷ 5 + 0.01 × low days, max 0.82 |
| **Divergence** | index at a 20-day high while VIX is not low → SELL; index at a 20-day low while VIX is not high → BUY | warning signal | 0.62 / 0.60 |

| Key (`volatility.`) | Default |
|---|---|
| `vix_spike_entry` | 22.0 |
| `spike_threshold_pct` | 20.0 |
| `nifty_drop_pct` | 3.0 |
| `vix_low_entry`, `vix_low_extreme` | 12.0, 10.0 |
| `consecutive_low_days` | 8 |
| `vix_lookback` | 20 |

## GIFT Nifty Gap

`gift_nifty_gap` · `strategies/gap/gift_nifty_gap.py` · regime: all

Uses the pre-market gap between GIFT Nifty and the previous Nifty close
([Market Intelligence](market-intelligence.md#gift-nifty)). It acts only in two
windows of the **wall-clock** time:

| Window (IST) | Gap | Action |
|---|---|---|
| 09:15–09:30 | weak (0.3 %–1.5 %) | **Fade** it: SELL a gap up, BUY a gap down |
| 09:31–10:30 | strong (≥ 1.5 %) | **Follow** it: BUY above the opening-range high after a gap up, SELL below the low after a gap down |

Gaps under 0.3 % are ignored. Stop 0.4 %, target 0.8 % (1.5 % for strong
gaps).

| Key (`gap.`) | Default |
|---|---|
| `fade_weak_gap`, `follow_strong_gap` | true, true |
| `stop_loss_pct` | 0.004 |
| `take_profit_pct`, `strong_take_profit_pct` | 0.008, 0.015 |

> **Effectively inactive.** There is no working GIFT Nifty price source (the
> fallback reads Nifty 50's own last price, which before the open is
> yesterday's close), so the gap is almost always below 0.3 % and the strategy
> stays silent. Because it uses the wall clock, it also never fires in
> backtests. The class docstring mentions tilting other strategies by a
> pre-market bias; the engine has no such mechanism.

## FII/DII Flow

`fii_dii` · `strategies/institutional/fii_dii_strategy.py` · regime: all

Follows institutional money:

1. `get_fii_sentiment(consecutive_days)` sums FII net cash buying over the
   last `consecutive_days` sessions.
2. If that is BULLISH or BEARISH and the daily average exceeds
   `fii_threshold_cr ÷ consecutive_days`, signal in that direction.
3. Stop 0.8 %, target 1.5 % of the index price; confidence 0.55 + daily
   average ÷ 5,000, max 0.85.

| Key (`institutional.`) | Default |
|---|---|
| `consecutive_days` | 3 |
| `fii_threshold_cr` | 1000.0 |
| `delivery_min_pct` | 45.0 |
| `block_counter_strong` | true |
| `size_boost_bullish`, `size_reduce_bearish` | 1.25, 0.75 |

The class also offers `get_stock_delivery_signal(symbol)` (a long bias for
stocks with high delivery % in bullish flow) and `get_size_multiplier()`.
Nothing calls them yet, so the delivery, blocking and sizing settings currently
have no effect.
