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

## Did the signals work?

`signals/outcomes.py` records what happened after the signals. The
`signal_outcomes` scheduler job runs it every weekday at 16:30 IST, or run
`python scripts/evaluate_signals.py` by hand. For the **last daily signal of
each stock on each trading day**, it records:

- the return 1, 5 and 20 trading days after that day's close;
- for bullish and bearish signals with a setup, whether the price reached
  `target_1` or `stop_loss` first, within 20 bars. If one bar touches both,
  the stop counts first; if neither is reached, the setup has `expired`.

A setup that hits its stop or expires gets `invalidated_at` set, and its
signal's `status` becomes `invalidated` (or `closed` on a target). Rows are
refreshed until every horizon has passed.

`performance(db, days)`, the API `GET /api/signals/performance`, and the
**Track record** view on the Signals page report:

| Table | Shows |
|---|---|
| By direction | Count; average 1/5/20-day return (direction-adjusted for bullish and bearish, so a fall after a bearish signal is a gain); 5-day hit rate; **excess** return over the baseline; setup targets, stops and expiries |
| By score band | For bullish + bearish signals: does a higher score do better? |
| Components | Correlation of each component score with the direction-adjusted 5-day return (needs 10 or more signals) |

The **baseline** is the average raw return of every evaluated signal: what
simply holding the stocks the engine looked at would have done over the same
days. A bullish average of +1 % means little if the baseline was +1.2 %.

```bash
python scripts/evaluate_signals.py --days 30
python scripts/evaluate_signals.py --report-only
```

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
  favour news-driven moves. Keep the sum at 1 so scores stay on 0–100. Check
  the [track record](#did-the-signals-work) first: a component whose score
  does not correlate with later returns is not earning its weight.
- **Which strategies feed Technical**: the engine uses your
  `strategies.enabled` list, so tuning the bot's strategies also changes the
  composite scores.

The [Signals page](../dashboard/signals.md) shows every component, and
[Why and the Copilot](why-and-copilot.md) explains how they are turned into
an explanation.
