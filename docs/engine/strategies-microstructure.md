# Microstructure Strategies

Strategies built on *how* trading happens — order flow, volume at price,
session VWAP and the order book — rather than on price trends alone. Their
settings live under a nested `microstructure:` section of the configuration
(`microstructure.anchored_vwap`, `microstructure.cumulative_delta`,
`microstructure.volume_profile`), except `order_book_imbalance`, which reads
top-level keys.

## Anchored VWAP

`anchored_vwap` · `strategies/microstructure/anchored_vwap.py` · regimes: ranging, trending up/down

`compute_anchored_vwap(df)` returns the session VWAP and volume-weighted ±1σ
and ±2σ bands, all restarting at each session. The strategy measures where
price sits in σ units from VWAP and picks one mode:

| Mode | Condition | Trade | Stop / target | Confidence |
|---|---|---|---|---|
| Reversion | ≥ +`reversion_sigma` | SELL back to VWAP | 0.8× ATR / VWAP | 0.60 + 0.1 per σ beyond, max 0.82 |
| Reversion | ≤ −`reversion_sigma` | BUY back to VWAP | 0.8× ATR / VWAP | same |
| Breakout | fresh cross above +`breakout_sigma` with volume ≥ `vol_confirm_mult` × average | BUY | 1× / 1.8× ATR | 0.58 + 0.05 × volume ratio, max 0.80 |
| Breakdown | fresh cross below −`breakout_sigma` with volume | SELL | 1× / 1.8× ATR | same |

| Key (`microstructure.anchored_vwap.`) | Default |
|---|---|
| `reversion_sigma` | 1.8 |
| `breakout_sigma` | 1.0 |
| `vol_confirm_mult` | 1.5 |
| `min_bars` | 10 |

Like VWAP reversion, it needs **at least three bars in the current session**
and stands aside on daily data, where session bands have no width.

## Cumulative Delta

`cumulative_delta` · `strategies/microstructure/cumulative_delta.py` · regime: all

Estimates order flow from OHLCV bars. Each bar's volume is split into buying
and selling by where it closed in its range:

```
buy volume  = volume × (close − low) ÷ (high − low)
sell volume = volume − buy volume
delta       = buy volume − sell volume
```

Over the last `window` bars (a `DeltaTracker` per symbol):

- **Divergence** (checked first) — over five bars, price up while cumulative
  delta falls by more than 10 % → bearish; price down while delta rises →
  bullish. Trades the reversal with 1× / 1.8× ATR; confidence 0.72.
- **Confirmation** — imbalance (delta ÷ volume) above
  `delta_threshold_pct` with price above the window's VWAP → BUY; below
  −threshold with price below VWAP → SELL. 1× / 1.5× ATR; confidence
  0.55 + imbalance ÷ 2, max 0.82.

| Key (`microstructure.cumulative_delta.`) | Default |
|---|---|
| `window` | 20 |
| `delta_threshold_pct` | 0.15 |
| `divergence_enabled` | true |

This is an approximation. True delta needs tick-by-tick trade direction; the
`DeltaTracker.add_tick()` method supports that when such data is available.
On daily bars it fires often, because a close near a bar's high or low is
common.

## Volume Profile

`volume_profile` · `strategies/microstructure/volume_profile.py` · regime: all

Builds a volume-at-price histogram (`bins` buckets) over the last
`lookback_bars` bars, finding the **POC** (point of control — most traded
price), the **value area** (VAH/VAL — the band holding 70 % of volume) and
high/low volume nodes. Candidate signals, best confidence wins:

| Setup | Condition | Trade | Confidence |
|---|---|---|---|
| POC bounce | within `poc_bounce_pct` of the POC | in the direction of the last 5 bars | 0.70 |
| Value-area breakout | fresh close above VAH × (1 + `vah_break_pct`) | BUY | 0.68 |
| Value-area breakdown | fresh close below VAL × (1 − `val_break_pct`) | SELL | 0.68 |
| HVN fade | at a high-volume node within `hvn_fade_pct` | against the last 3 bars | 0.63 |

| Key (`microstructure.volume_profile.`) | Default |
|---|---|
| `lookback_bars` | 60 |
| `bins` | 100 |
| `poc_bounce_pct` | 0.003 |
| `vah_break_pct`, `val_break_pct` | 0.002 |
| `hvn_fade_pct` | 0.004 |

`compute_volume_profile(df, bins)` is reusable on its own (`.poc`, `.vah`,
`.val`, `.value_area_pct`, nodes).

## Order Book Imbalance

`order_book_imbalance` · `strategies/microstructure/order_book_imbalance.py` · regime: all

Needs a live `orderbook=` snapshot (an `OrderBookSnapshot`):

```
score = 0.6 × imbalance(top N levels) + 0.4 × whale pressure
```

Score above `ob_imbalance_threshold` → BUY, below its negative → SELL, with a
tight 1.2× / 1.8× ATR stop and target; confidence = |score|.

| Key | Default |
|---|---|
| `ob_imbalance_threshold` | 0.3 |
| `ob_depth` | 10 levels |
| `whale_threshold_usd` | 100,000 |

> Neither the bot nor the backtester passes an order book, so this strategy
> never fires today. Wiring it requires fetching depth
> (`UpstoxDataEngine.get_market_depth()`) and passing it via
> `extra_kwargs={"orderbook": snapshot}`.
