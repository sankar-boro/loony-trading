# Mean Reversion and Breakout Strategies

Mean-reversion strategies bet that a stretched price snaps back; they run only
in ranging (or low-volatility) regimes. Breakout strategies bet that a price
leaving a range keeps going.

## RSI Mean Reversion

`rsi_mean_reversion` · `strategies/mean_reversion/rsi_reversion.py` · regime: ranging

- **BUY** when RSI was below `rsi_oversold` on the previous bar and has turned
  up; confidence = how deep it was, `(oversold − RSI) ÷ oversold`.
- **SELL** when RSI was above `rsi_overbought` and has turned down.
- Stop 1.5× ATR, target 2.5× ATR.

| Key | Default |
|---|---|
| `rsi_period` | 14 |
| `rsi_oversold` / `rsi_overbought` | 30 / 70 |

## Bollinger Reversion

`bollinger_reversion` · `strategies/mean_reversion/bollinger_reversion.py` · regime: ranging

- **BUY** when price is in the bottom 5 % of the bands (%B < 0.05) and RSI <
  40; stop one ATR below the lower band; target the middle band.
  Confidence = 1 − %B.
- **SELL** when %B > 0.95 and RSI > 60; stop one ATR above the upper band;
  target the middle band. Confidence = %B.

| Key | Default |
|---|---|
| `bb_period` | 20 |
| `bb_std` | 2.0 |

## Z-Score Reversion

`zscore_reversion` · `strategies/mean_reversion/zscore_reversion.py` · regime: ranging

Rolling z-score of the close over `zscore_window` bars: below
−`zscore_entry` → BUY, above +`zscore_entry` → SELL. Confidence = |z| ÷ 4,
capped at 1. Stop 1.5× ATR, target 2× ATR.

| Key | Default |
|---|---|
| `zscore_window` | 20 |
| `zscore_entry` | 2.0 |
| `zscore_exit` | 0.5 (read but not used) |

## VWAP Reversion

`vwap_reversion` · `strategies/mean_reversion/vwap_reversion.py` · regimes: ranging, low volatility

An **intraday** strategy. Computes the session VWAP and bands at
± `vwap_std_mult` standard deviations (volume-weighted, reset each session):

- **BUY** when price is below the lower band — stop 1.5× ATR below, target
  VWAP.
- **SELL** above the upper band — stop 1.5× ATR above, target VWAP.
- Confidence 0.65. Key `vwap_std_mult` (1.5).

It **stands aside unless the current session has at least two bars**. On daily
bars a session is one bar, its VWAP equals that bar's typical price and the
bands have zero width, so before this guard the strategy fired on every single
daily bar. It now only trades on intraday data — the live bot's
`timeframes.intraday` frames, or intraday backtests.

## ATR Breakout

`breakout_atr` · `strategies/breakout/atr_breakout.py` · regime: volatile

A volatility squeeze release: ATR(14) is now more than `atr_expansion_mult`
times its `squeeze_window` average, after having been below 0.8× within the
last three bars. Direction from the last bar's change. Stop 1.5× ATR, target
3× ATR. Confidence = ATR ratio ÷ 3.

| Key | Default |
|---|---|
| `squeeze_window` | 20 |
| `atr_expansion_mult` | 1.5 |

## Opening Range Breakout

`range_breakout` · `strategies/breakout/range_breakout.py` · regimes: ranging, trending

On NSE intraday data — a datetime index whose first bar today falls between
09:00 and 09:30 IST — the opening range is the high and low of today's first
`range_minutes` minutes. A later bar closing more than 0.1× ATR above the range
high is a BUY, below the low a SELL. Confidence 0.68.

On data that does not look like an NSE session (daily bars, 24/7 crypto) it
falls back to the older rule: the range of `range_bars` bars ending five bars
ago.

| Key | Default |
|---|---|
| `range_minutes` | 15 |
| `range_bars` | 8 (fallback) |

## Support/Resistance Breakout

`sr_breakout` · `strategies/breakout/support_resistance.py` · regimes: trending, volatile

1. Finds swing highs and lows (the extreme of a ±`swing_window` bar window).
2. Clusters levels within 0.5 % of the average price and counts touches;
   keeps the five most-touched.
3. For levels with at least `sr_min_touches` touches: a close
   `confirm_bars` bars ago on one side and now more than 0.5× ATR through
   the level is a breakout (BUY through resistance, SELL through support).
4. Confidence 0.70 + 0.05 per touch (max 0.95).

| Key | Default |
|---|---|
| `swing_window` | 10 |
| `confirm_bars` | 2 |
| `sr_min_touches` | 2 |
