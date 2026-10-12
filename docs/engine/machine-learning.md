# Machine Learning

The ML layer trains a classifier to predict whether a stock will rise, fall or
go nowhere over the next five bars, and exposes it as the `ml_classifier`
strategy. Its central design rule: **a model is only used if it beats naive
baselines on data it was never trained on.**

## Current status

The latest training run (10 large caps × 2 years of daily bars, 51 features)
reached **40.9 % out-of-sample accuracy against 48.7 % for always predicting
the most common class**. It did not pass, so no model was saved and
`ml_classifier` is not enabled. The pipeline is ready for better inputs —
intraday bars, other horizons, news or flow features — judged by the same
gate.

## The problem setup

`ml_models/dataset.py` is the single definition of the ML inputs, shared by
training and live prediction:

| Element | Definition |
|---|---|
| Features | The ~50 columns of `FeatureBuilder.build()` ([Features](features.md#the-standard-feature-set)), excluding raw OHLCV and open interest |
| Label | Return over the next `FORWARD_BARS` = 5 bars: above +0.5 % → **buy** (2), below −0.5 % → **sell** (0), otherwise **hold** (1) |
| Unknown future | The last 5 bars have no label (NaN) and are dropped — not labelled "hold" |

Training and prediction must use exactly the same columns in the same order;
the trained model stores its `feature_cols`, and prediction reads them.

## Honest evaluation

`make_dataset(frames)` splits **each symbol by time**: the first 80 % of its
bars for training, the last 20 % for testing, with a 5-bar gap between them
so no training label looks into the test period. The test set is therefore
genuinely later data for every stock — not other stocks over the same dates.

`evaluate()` reports, on the test set:

| Metric | Meaning |
|---|---|
| `accuracy` | Share of correct predictions |
| `baseline_accuracy` | Accuracy of always predicting the most common training class |
| `trade_calls`, `trade_precision` | How many buy/sell calls, and how often they were right — the only predictions the strategy trades |
| `trade_baseline` | Hit rate of blindly calling the more common move (buy or sell) every time |

`passes_gate(report)` requires at least one trade call, accuracy above the
majority baseline **and** trade precision above the trade baseline.

## Training

```bash
python scripts/train_ml.py                       # 10 default large caps, 730 days
python scripts/train_ml.py --symbols TCS,INFY,WIPRO --days 1000
python scripts/train_ml.py --enable              # also enable ml_classifier if it passes
python scripts/train_ml.py --save-anyway         # save even if it fails the gate (experiments)
python main.py --mode train                      # same gated training
./loony.sh train
```

`retrain()` (in `scripts/train_ml.py`):

1. Fetches daily candles for each symbol (`--days` of history).
2. Builds the dataset and trains an **XGBoost** and a **LightGBM** classifier
   on the training split (each uses its own internal early-stopping split).
3. Combines them in an equal-weight soft-voting `EnsembleModel`.
4. Evaluates on the held-out split and prints the report.
5. **Only if it passes** (or `--save-anyway`): saves `models/ensemble.pkl`
   (model, feature columns, symbols, sample count, report, timestamp) plus
   `models/xgboost.pkl` and `models/lightgbm.pkl`.
6. With `--enable` and a passing model, adds `ml_classifier` to
   `strategies.enabled` in `config/settings.yaml` (preserving comments).

Training uses fixed hyperparameters (XGBoost 300 trees, depth 5, learning
rate 0.05; LightGBM 63 leaves, 300 trees, 0.05). The `ml.xgboost` /
`ml.lightgbm` settings are read only by `ModelTrainer`, the older single-symbol
trainer.

It needs no trading token: the historical-candle endpoint it uses works
without one on the accounts tested.

### Weekly retraining

The scheduler's `ml_retrain` job runs the same `retrain()` every Sunday at
06:00 IST. It replaces `models/ensemble.pkl` only with a model that passes the
gate and never enables the strategy; a running bot picks the new model up on
its next start. See [The Scheduler](../marketpulse/scheduler.md).

## Using a model

At startup the `MetaStrategyEngine` loads `models/ensemble.pkl` if present;
`main.py` falls back to `models/xgboost.pkl` + `lightgbm.pkl`. The bot never
trains at startup. The `ml_classifier` strategy then predicts on every scoring
pass — see [Corporate Events and ML](strategies-corporate-ml.md#ml-classifier).

## Model classes

`ml_models/` — all share the `BaseMLModel` interface (`train`, `predict`,
`predict_proba`, `save`, `load`, `feature_cols`); models save to the project's
`models/` directory.

| Class | File | Notes |
|---|---|---|
| `XGBoostModel` | `xgb_model.py` | Gradient-boosted trees, 3-class |
| `LightGBMModel` | `lgbm_model.py` | Same interface, faster |
| `EnsembleModel` | `ensemble.py` | Weighted soft voting; `update_weights_by_accuracy(X, y)` |
| `LSTMModel` | `lstm_model.py` | Sequence model (`ml.lstm`); needs TensorFlow (not installed by default). Predicting on a single row returns "hold" — it needs `sequence_length` rows |
| `TemporalFusionTransformer` | `tft_model.py` | Pure NumPy TFT with attention and multi-horizon output; research code |
| `AdaptiveModel`, `OnlineEnsemble` | `online_model.py` | Online learning that updates after each outcome; uses River if installed, else a perceptron fallback. `ADWINDetector` and `PageHinkleyDetector` detect concept drift |
| `RLTradingAgent` | `rl_agent.py` | PPO agent on a custom trading environment; needs stable-baselines3 + gymnasium. A skeleton |
| `BayesianOptimizer` | `bayesian_opt.py` | Tunes strategy parameters against your backtest function — Optuna TPE if installed, else a Gaussian-process surrogate. Helpers `optimize_pair_trading()`, `optimize_vix_strategy()` |
| `ModelTrainer` | `trainer.py` | Older single-frame trainer (time split, ensemble weights from the held-out part) |

Only XGBoost, LightGBM and the ensemble are part of the production pipeline;
the rest are libraries and experiments.

## Improving the model

Ideas, each to be judged by the same out-of-sample gate:

- **Intraday bars** (30-minute), where microstructure features matter more.
- **Different horizons and thresholds** — five days and ±0.5 % is one arbitrary
  choice; avoid tuning these against the test set, or you will overfit it.
- **Point-in-time context features** — VIX, FII flows and news scores stored
  per historical date (the current "advanced" features cannot be used for
  training because they hold today's values on every row).
- **More symbols and longer history.**
