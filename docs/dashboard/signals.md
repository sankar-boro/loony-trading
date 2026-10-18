# Signals

The Signals page (`/signals`, `pages/Signals.tsx`) shows the MarketPulse
**composite signal** for every stock: a 0–100 score blending news, technicals,
momentum, volume, history, market regime and risk, with a direction and, for
actionable signals, a trade setup. It needs the database and scored signals
(`python scripts/run_signal_engine.py`, or the scheduler).

## The list

`GET /api/signals/composite?timeframe=…&direction=…` (every 60 s) returns one
row per stock — its most recent signal for the chosen timeframe — sorted by
score.

| Control | Options |
|---|---|
| Direction filter | all, bullish, bearish, watch, no_signal |
| Timeframe | Daily (`1d`), 30 min (`30m`), 1 hour (`1h`) |

Daily signals come from the regular signal engine run. Intraday rows only exist
after an intraday scan — from the [Intraday Lab](intraday-lab.md), the
intraday scheduler track, or `run_signal_engine.py --timeframe 30m` — and the
page says so when an intraday timeframe is empty. Daily and intraday signals
are stored separately (the `timeframe` column), so an intraday scan never
changes the daily view.

### Directions

| Direction | Condition |
|---|---|
| **Bullish** / **Bearish** | A strategy fired, the composite score ≥ `quality_gate.min_score` (70) **and** the strategy's confidence ≥ `min_confidence` (65). Direction follows the strategy's BUY/SELL |
| **Watch** | A strategy fired and the score ≥ `watch_score` (50), but the full gate was not met |
| **No signal** | No strategy fired, or the score is below 50 |

Most stocks are expected to be **No signal** on most days: the engine is
designed for a few explainable opportunities, not many weak ones.

## The detail panel

Click a row to load `GET /api/signals/composite/{id}`:

### Score breakdown

Each of the seven components with its 0–100 value, its weight and its
contribution (value × weight), summing to the **Total**:

| Component | Weight | What it measures |
|---|---|---|
| Catalyst | 25 % | Strongest relevant news event in the last 3 days |
| Technical | 20 % | Confidence of the best strategy signal |
| Momentum | 15 % | Distance of RSI(14) from 50 |
| Volume | 15 % | Today's volume vs the 20-bar average |
| Historical | 10 % | How often similar past news events closed higher the next day |
| Regime | 10 % | Whether the market regime suits the signal's direction |
| Risk | 5 % | Lower volatility (ATR as % of price) scores higher |

Weights come from `signal_engine.weights` in `config/settings.yaml`. The exact
formulas are in [Composite Signals](../marketpulse/composite-signals.md).

### Trade setup

Bullish and bearish signals carry a setup derived from the winning strategy's
ATR-based stop and target:

| Field | Definition |
|---|---|
| Entry zone | Signal price ± 0.15 × ATR(14) |
| Stop loss | The strategy's stop |
| Target 1 | The strategy's take-profit |
| Target 2 | 1.5 × the distance to target 1 |
| Risk/reward | Distance to target 1 ÷ distance to the stop |

These are research outputs, not orders — the trading bot does not read them.

## Track record

The **Track record** button switches the page to how past daily signals did,
over the last 30, 90 or 180 days:
- by direction: average returns, hit rate, excess over the baseline, and
  setup targets / stops / expiries;
- by score band;
- each component's correlation with later returns.

Outcomes are recorded every weekday at 16:30 IST, so the view starts empty
and fills in a day after the first signals. See
[Did the signals work?](../marketpulse/composite-signals.md#did-the-signals-work).
