# Trend and Momentum Strategies

Strategies that join a move already under way. All of them return a BUY or
SELL with ATR-based stops (2× ATR stop, 3× ATR target unless stated) and are
silenced outside their preferred regime.

## EMA Crossover

`ema_crossover` · `strategies/trend/ema_crossover.py` · regime: trending

- **BUY** when the fast EMA crosses above the slow EMA (golden cross);
  **SELL** on the opposite cross (death cross).
- Only if ADX ≥ `adx_min` — a trend must exist.
- Confidence = ADX ÷ 50, capped at 1.

| Key | Default |
|---|---|
| `ema_fast` | 9 |
| `ema_slow` | 21 |
| `adx_min` | 20 |

## Supertrend

`supertrend` · `strategies/trend/supertrend.py` · regime: trending

Fires when the Supertrend direction flips between the last two bars: up-flip
→ BUY, down-flip → SELL. Confidence 0.75.

| Key | Default |
|---|---|
| `st_period` | 7 |
| `st_multiplier` | 3.0 |

## Donchian Breakout

`donchian_breakout` · `strategies/trend/donchian_breakout.py` · regime: trending

Turtle-style channel breakout: **BUY** when the close exceeds the previous
bar's `dc_period`-bar high, **SELL** when it falls below the previous low.
Confidence 0.70. Key `dc_period` (20).

## Multi-Timeframe Trend

`mtf_trend` · `strategies/trend/multi_timeframe_trend.py` · regime: trending

Requires a `frames={timeframe: DataFrame}` argument. For each frame with ≥ 50
bars it takes the trend as EMA(20) vs EMA(50); with at least two frames all
agreeing, it signals in that direction with confidence 0.85.

> The bot and backtester call strategies without `frames`, so `mtf_trend`
> never fires there. It is usable from your own code via
> `engine.generate_signals(sym, df, extra_kwargs={"frames": {...}})`.

## MACD Momentum

`macd_momentum` · `strategies/momentum/macd_momentum.py` · regime: trending

- **BUY** when the MACD histogram turns positive, **SELL** when it turns
  negative — only with volume > 1.1× its 20-bar average.
- Confidence 0.70, or 0.85 if the histogram is still growing.

| Key | Default |
|---|---|
| `macd_fast` / `macd_slow` / `macd_signal` | 12 / 26 / 9 |

## RSI Momentum

`rsi_momentum` · `strategies/momentum/rsi_momentum.py` · regime: trending

RSI(14) crossing 50 in the direction of the trend: up-cross with price above
EMA(50) → BUY; down-cross below EMA(50) → SELL. Confidence 0.65. No keys.

## Volume Momentum

`volume_momentum` · `strategies/momentum/volume_momentum.py` · regimes: trending, volatile

A price move confirmed by a volume spike and on-balance volume:

- **BUY**: volume > `vol_spike_mult` × 20-bar average, close up more than
  `price_move_pct`, OBV higher than two bars ago.
- **SELL**: the mirror image.
- Confidence 0.72.

| Key | Default |
|---|---|
| `vol_spike_mult` | 2.0 |
| `price_move_pct` | 0.01 (1 %) |

## Candle Patterns

`candle_patterns` · `strategies/candlestick/candle_strategy.py` · regime: all

Runs the candlestick detector (engulfing, doji, hammer, stars, three soldiers /
crows) and the chart detector (double top/bottom, head and shoulders). Takes
the strongest pattern formed within the last three bars with strength ≥
`pattern_min_strength` (0.65) and trades its direction, with a tighter 1.5×
ATR stop and 2.5× ATR target. Confidence = the pattern's strength; the pattern
name is in `metadata["pattern"]`.

Patterns are frequent on noisy data, so this strategy fires often; its low
default weight (0.7) keeps it from dominating.
