# Composite Signals

The composite signal engine (`signals/composite.py`, `CompositeSignalEngine`)
gives every stock a single 0–100 score from seven independent components,
classifies it as bullish, bearish, watch or no signal, and attaches a trade
setup to actionable signals.

## Running it

```bash
python scripts/run_signal_engine.py                       # whole universe, daily bars
python scripts/run_signal_engine.py --limit 10            # first 10 stocks
python scripts/run_signal_engine.py --timeframe 30m --lookback-days 5
```

`run_signal_engine(limit, lookback_days=200, timeframe="1d", symbols=None)` is
the single entry point used by the CLI, the scheduler and the Intraday Lab.
For each stock it fetches candles through `UpstoxDataEngine.fetch_ohlcv`
(cache first, then Upstox, or demo data without a token), skips stocks with
fewer than 50 bars, scores, stores and commits per stock — a failure on one
stock is logged and does not roll back the others. It returns:

```json
{ "universe": 91, "scored": 88, "skipped": 3, "timeframe": "1d",
  "directions": { "bullish": 2, "bearish": 1, "watch": 9, "no_signal": 76 },
  "results": [ … ], "errors": [ { "symbol": "XYZ", "error": "only 12 bars — need 50+" } ] }
```

## The seven components

Each component is a number from 0 to 100.

| Component | Weight | Formula |
|---|---|---|
| **Catalyst** | 0.25 | The stock's most significant news link in the last 3 days, ranked by relevance × catalyst score: `catalyst_score (0–10) × 10 × relevance`. 0 with no recent news |
| **Technical** | 0.20 | Confidence of the best strategy signal from the `MetaStrategyEngine` (the same strategies the bot trades), × 100. 0 when no strategy fires |
| **Momentum** | 0.15 | `abs(RSI(14) − 50) ÷ 50 × 100` — strength of momentum in either direction |
| **Volume** | 0.15 | `(relative volume − 1) × 50 + 50`, where relative volume = latest bar ÷ 20-bar average; clamped to 0–100. 50 = average, 100 = double |
| **Historical** | 0.10 | Win rate at the 1-day horizon of past events with the same type and direction as the current catalyst — only with ≥ 5 samples; otherwise a neutral 50 |
| **Regime** | 0.10 | Fit between the market regime and the signal direction: trend in the signal's direction 80, against it 20, ranging 60, low volatility 55, high volatility 35; 50 with no signal or too little data |
| **Risk** | 0.05 | `100 − ATR%(14) × 1500`, clamped — calmer stocks score higher (ATR of 2 % of price → 70) |

**Score** = Σ component × weight. Weights come from `signal_engine.weights` in
`config/settings.yaml` and should sum to 1.

## Direction and the quality gate

```yaml
signal_engine:
  quality_gate:
    min_score: 70
    min_confidence: 65
    watch_score: 50
```

| Result | Rule |
|---|---|
| **No signal** | No strategy fired (confidence 0) |
| **Bullish / Bearish** | score ≥ `min_score` **and** strategy confidence ≥ `min_confidence`; direction from the strategy's BUY/SELL |
| **Watch** | otherwise, if score ≥ `watch_score` |
| **No signal** | otherwise |

The stored `confidence` is the firing strategy's confidence × 100, not a
separate model. Because a strategy must fire for anything but *No signal*, news
alone can never create a bullish signal — it can only strengthen one.

## Trade setup

For bullish and bearish signals:

| Field | Value |
|---|---|
| `entry_low`, `entry_high` | Strategy price ∓ 0.15 × ATR(14) |
| `stop_loss` | The strategy's ATR-based stop |
| `target_1` | The strategy's take-profit |
| `target_2` | Price + 1.5 × (target 1 − price) |
| `risk_reward` | Distance to target 1 ÷ distance to stop |

## Timeframes

`score_symbol(..., timeframe=...)` tags every stored row. Daily (`1d`) is the
default everywhere; intraday rows (`30m`, `1h`) are written only when asked for,
and all readers filter by timeframe, so intraday scoring never changes the
daily view. Upstox's 5- and 15-minute historical candles fail with HTTP 400 on
some accounts, which is why the intraday defaults are 30 minutes.

## Tuning

- **More or fewer actionable signals**: move `min_score` / `min_confidence`.
  Lowering them produces more bullish/bearish rows of lower quality.
- **What matters most**: change `weights` — for example raise `catalyst` to
  favour news-driven moves. Keep the sum at 1 so scores stay on 0–100.
- **Which strategies feed Technical**: the engine uses your
  `strategies.enabled` list, so tuning the bot's strategies also changes the
  composite scores.

The [Signals page](../dashboard/signals.md) shows every component, and
[Why and the Copilot](why-and-copilot.md) explains how they are turned into
an explanation.
