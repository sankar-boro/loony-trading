# Corporate Events and ML Strategies

## ML Classifier

`ml_classifier` · `strategies/ml_based/ml_strategy.py` · regime: all

Turns the trained model's prediction for the latest bar into a signal:

1. Builds the standard feature set for the frame and takes the latest row **in
   exactly the columns, and order, the model was trained on** (the model's
   saved `feature_cols`). If a trained column is missing, it returns nothing.
2. `predict_proba` gives probabilities for sell / hold / buy.
3. The most likely class wins; **hold**, or a probability below
   `ml_min_confidence` (default 0.6, a top-level key), produces nothing.
4. Otherwise BUY or SELL with the standard 2× / 3× ATR stop and target;
   confidence = the class probability; `metadata["model"]` names the model.

Prediction errors are logged once per error type (they used to be swallowed
silently).

The model is loaded automatically from `models/ensemble.pkl` when the engine is
built. **It is not enabled by default and no model is shipped**: the latest
training run did not beat naive baselines, so the gated training refused to
save it. How to train, evaluate and enable it is in
[Machine Learning](machine-learning.md).

## PEAD — Post-Earnings Announcement Drift

`pead` · `strategies/corporate/pead_strategy.py` (`PEADStrategy`)

Stocks tend to keep drifting in the direction of an earnings surprise for weeks
after the announcement. The strategy scores surprises and trades the drift.

**Earnings surprise score**:

```
ESS = (actual EPS − consensus EPS) ÷ |consensus EPS| × 100
```

| ESS | Classification | Action |
|---|---|---|
| > +threshold (5 %) | positive surprise | long from the next day's open |
| > strong threshold | strong positive | long, larger size (`size_multiplier`) |
| < −threshold | negative surprise | short |
| in between | no trade | — |

Positions are held for the drift window (about 30 trading days) or until
`should_exit()` says momentum has faded. Thresholds come from
`surprise_threshold_pct`, `strong_surprise_pct` and `drift_window_days`.

| Method | Purpose |
|---|---|
| `add_earnings_surprise(symbol, actual, consensus, date)` | Feed one result |
| `generate_signal_from_surprise(...)` | Signal for a surprise |
| `scan_earnings_calendar()` | Look for upcoming results via NSE corporate actions |
| `active_positions()`, `position_summary()`, `should_exit()` | Position tracking |
| `backtest_pead(...)` | Evaluate on a list of historical surprises |

> **Not wired.** PEAD needs consensus EPS estimates, which no data source in
> the project provides, so surprises must be added by hand. It is not
> registered in the engine. See [Project Status](../appendix/status.md).
