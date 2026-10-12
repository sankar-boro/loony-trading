# Features and Indicators

`feature_engine/` turns raw OHLCV bars into the indicators strategies read
and the inputs the ML model learns from. Everything is plain pandas/NumPy — no
TA-Lib needed.

## Technical indicators

`feature_engine/indicators.py`, class `TechnicalIndicators` (imported as `TI`
throughout), all static methods:

| Method | Returns |
|---|---|
| `ema(s, n)`, `sma(s, n)`, `wma(s, n)` | Moving averages |
| `rsi(s, 14)` | Relative Strength Index, Wilder smoothing |
| `macd(s, 12, 26, 9)` | `(macd, signal, histogram)` |
| `stochastic(df, 14, 3)` | `(%K, %D)` |
| `cci(df, 20)` | Commodity Channel Index |
| `roc(s, 10)` | Rate of change, % |
| `atr(df, 14)` | Average True Range |
| `bollinger_bands(s, 20, 2)` | `(upper, mid, lower)` |
| `keltner_channels(df, 20, 10, 2)` | `(upper, mid, lower)` — EMA ± multiple × ATR |
| `adx(df, 14)` | `(ADX, +DI, −DI)` |
| `supertrend(df, 7, 3)` | `(line, direction)` with direction +1/−1 |
| `donchian_channel(df, 20)` | `(upper, mid, lower)` |
| `obv(df)` | On-balance volume |
| `vwap(df)` | Volume-weighted average price, **reset each session** |
| `vwap_bands(df, 2)` | `(upper, vwap, lower)` |
| `pivot_points(df)` | Classic floor pivots: pivot, R1–R3, S1–S3 |
| `session_cumsum(s, index)` | Cumulative sum that restarts each calendar day |

### Session-anchored VWAP

VWAP and its bands use `session_cumsum`, which restarts at each new trading
day when the index is a `DatetimeIndex`. A VWAP accumulated across several
days is not a valid intraday reference; this keeps intraday strategies honest
on multi-day frames. Without a datetime index it falls back to a plain
cumulative sum.

## The standard feature set

`FeatureBuilder().build(df)` (`feature_engine/feature_builder.py`) adds about
50 columns and drops rows where any feature is still undefined. **It needs at
least ~200 bars**, because `ema_200` is undefined before that; shorter
frames come back much shorter or empty.

| Group | Columns |
|---|---|
| Moving averages | `ema_9/20/50/200`, `sma_9/20/50`, `vwap`, `ema_cross_9_20`, `ema_cross_20_50`, `ema_cross_50_200` (sign of the difference) |
| Oscillators | `rsi_7/14/21`, `macd`, `macd_signal`, `macd_hist`, `macd_cross`, `stoch_k`, `stoch_d`, `cci`, `roc_10`, `roc_20` |
| Volatility | `atr_14`, `atr_pct`, `bb_upper/mid/lower`, `bb_width`, `bb_pct` (0 = lower band, 1 = upper), `historical_vol` (20-bar, annualised) |
| Volume | `obv`, `volume_sma_20`, `volume_ratio`, `vwap_diff` |
| Trend | `adx`, `di_plus`, `di_minus`, `supertrend`, `supertrend_dir`, `dc_upper`, `dc_lower`, `dc_pct` |
| Price | `return_1/5/10`, `zscore_20`, `zscore_50`, `hl_range_pct`, `close_position` (close within the bar's range), `gap` (open vs previous close) |

Strategies mostly compute what they need from OHLCV themselves, so they work
on frames with or without these columns. The ML model is trained and run on
exactly this set — see [Machine Learning](machine-learning.md).

### Multi-timeframe features

`build_multitimeframe(frames, primary_tf)` builds the primary frame and adds
`rsi_14`, `adx`, `macd_hist`, `bb_pct` and `supertrend_dir` from each other
timeframe as `<col>_<tf>`, forward-filled onto the primary index.

## Advanced features

`FeatureBuilder().advanced_build(df, symbol)` →
`AdvancedFeatureBuilder` (`feature_engine/advanced_features.py`) adds
market-context columns on top of the standard set:

| Group | Columns | Source |
|---|---|---|
| India VIX | `vix_level`, `vix_1d_change`, `vix_5d_change`, `vix_percentile`, `vix_regime` (−2 … +2) | NSE VIX history |
| Institutional flow | `fii_net_5d`, `dii_net_5d`, `fii_signal` (+1/0/−1) | NSE FII/DII |
| Macro | `usdinr_ret`, `gold_ret`, `crude_ret`, their 20-day z-scores, `vix_us` | Upstox MCX/NSE, Yahoo Finance fallback; cached daily in `data/feature_cache/` |
| Delivery | `delivery_pct` (50 if unknown) | NSE bhav copy |
| Options (with a chain) | OI build-up, PCR, skew, max-pain distance | `compute_oi_features()` |

> **Use for the latest bar only.** These values are fetched once — *today's*
> VIX, flows, macro moves and delivery — and written onto **every row** of the
> frame. They describe the present, not each historical bar, so training a
> model on them leaks today's information into the past. The ML pipeline
> therefore trains on the standard set only.

## Candlestick and chart patterns

`feature_engine/pattern_detector.py`:

- `CandlestickPatternDetector().detect_all(df)` — engulfing, doji, hammer /
  shooting star, morning / evening star, three white soldiers / black crows.
  Each `PatternSignal` has a name, bar index, direction and strength. Used by
  the [candle_patterns strategy](strategies-trend-momentum.md#candle-patterns).
- `ChartPatternDetector` — double top / bottom and head-and-shoulders from local
  peaks and troughs.

## Options Greeks

`feature_engine/greeks.py` implements Black-Scholes:

```python
from feature_engine.greeks import Greeks, implied_volatility
g = Greeks(S=24000, K=24000, T=30, r=0.065, sigma=0.15, opt="call")   # T in calendar days
g.price, g.delta, g.gamma, g.theta, g.vega, g.rho        # first order
g.vanna, g.charm, g.speed, g.color, g.vomma              # second / third order
g.intrinsic(), g.time_value(), g.moneyness()             # ITM / ATM / OTM

iv = implied_volatility(market_price=250, S=24000, K=24000, T=30, r=0.065, opt="call")
```

Also `iv_rank(current, history)`, `iv_percentile(current, history)` and
`delta_to_strike(...)` (the strike with a target delta). The implied-volatility
solver uses Newton-Raphson. Used by the options strategies and the IV surface.

## Kalman filter

`utils/kalman.py` provides a Kalman filter for a time-varying hedge ratio
between two price series — the core of
[pair trading](strategies-stat-arb.md).
