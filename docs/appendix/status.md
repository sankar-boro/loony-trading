# Implementation Status & Open Issues

Single checklist for what is built, what is still to do, and the bugs found in the
code. It replaces the old `todo.md`, `todo/` (P1–P4 gap audit) and `known_issues.md`.

**Last verified against the code:** 2026-10-09 (commit `3fd55bd`).
Offline test suite: **521 tests, all passing**.

Legend: `[x]` done and verified in code · `[ ]` open (todo, partial, or a bug).

---

## Contents

- [1. Done — gap audit (P1–P4)](#1-done--gap-audit-p1p4)
- [2. Done — other implemented work](#2-done--other-implemented-work)
- [3. Remaining work](#3-remaining-work)
- [4. Bugs found in the code](#4-bugs-found-in-the-code)
- [5. Documentation problems](#5-documentation-problems)
- [6. Strategy status](#6-strategy-status)

---

## 1. Done — gap audit (P1–P4)

### P1 · Critical (before first live trade)

- [x] Daily token renewal script: `scripts/auto_login.sh` (cron entry documented in its header)
- [x] Token age check at startup in `main.py` (hard block in live mode, warning in paper mode)
- [x] MIS squareoff helper `should_squareoff_mis()` in `utils/timeutils.py` (3:14 PM IST)
- [x] MIS squareoff in `scripts/paper_trade.py`, once per session
- [x] MIS squareoff in `main.py` live loop calling `UpstoxExecutor.squareoff_all_mis()`
- [x] Paper position state saved to `data/live_positions.json` every tick and restored on restart (<1h old)
- [x] Market-hours guard in `paper_trade.py`, `live_signals.py`, `market_watch.py` and `main.py`

### P2 · Trading correctness

- [x] Corporate-action adjustments: `data_engine/upstox/corporate_actions.py`, applied in `UpstoxDataEngine.fetch_ohlcv()`
- [x] Realistic NSE charges (`_compute_charges()`, MIS ≈0.055%, CNC ≈0.21% round trip)
- [x] Backtester uses `commission_intraday` / `commission_delivery` from config
- [x] Intraday data refresh in `paper_trade.py` (`_refresh_intraday()`)
- [x] Options key resolver: `data_engine/upstox/options_resolver.py`
- [x] Multi-leg orders: `UpstoxExecutor.place_basket_order()`
- [x] F&O lot sizes: `FO_LOT_SIZES` + `snap_to_lot()` in `risk_manager.py`, `_validate_quantity()` before every order

### P3 · Observability

- [x] Telegram alerts wired into `paper_trade.py` and `live_signals.py`
- [x] `main.py` sends trade / close notifications through `utils.notifier.Notifier`
- [x] End-of-day report at 3:35 PM IST → `data/daily_pnl.jsonl` + Telegram summary
- [x] `scripts/daily_report.py`
- [x] `scripts/trade_journal.py` (by strategy / symbol / date, CSV export)
- [x] Benchmark comparison (alpha, beta, information ratio vs Nifty 50) in `backtest_runner.py`

### P4 · Infrastructure

- [x] NSE holidays fetched from NSE and cached to `data/nse_holidays.json`, with a 2026 fallback list in `settings.yaml`
- [x] Protobuf decoder check (`_check_protobuf_decoder()`) in `upstox_feed.py`
- [x] Streamlit dashboard replaced by FastAPI + React (`dashboard/`)
- [x] Equity curve written to `data/equity_curve.jsonl` and shown on the dashboard
- [x] `scripts/tune_weights.py`; non-uniform, backtest-derived weights in `settings.yaml`

### Intraday audit ([intraday_gaps.md](intraday_gaps.md))

- [x] Live tick loop refreshes strategy data from a live bar aggregator (`data_engine/live_bars.py`)
- [x] Session-aware VWAP / anchored VWAP (`session_cumsum()`)
- [x] Opening Range Breakout anchored to the 09:15 IST open
- [x] Backtester simulates MIS squareoff at 15:14 IST
- [x] Order placement and status polling moved off the event loop (`_post_async` etc.)
- [x] Timeframe parameter for composite signals and alerts (`Signal.timeframe` column)
- [x] Opt-in intraday scheduler track (`scheduler.intraday_*`)

---

## 2. Done — other implemented work

- [x] Docker files updated for FastAPI + React (port 8000), Postgres and Redis services
- [x] Docker healthcheck hits `GET /api/health`
- [x] `requirements.txt` cleaned (no Streamlit)
- [x] Scripts read `config/settings.yaml` (enabled strategies and weights)
- [x] `advanced_features.py` wired into `FeatureBuilder`
- [x] Anchored VWAP, cumulative delta and volume profile strategies added to `MetaStrategyEngine`
- [x] HMM regime detector used as the primary method in `RegimeDetector`
- [x] HMM regime tests (`tests/test_p6_p14.py::TestHMMRegime`)
- [x] `loony.sh status` fixed (no invalid `--quiet` flag)
- [x] `.env.example` added
- [x] Old Streamlit `dashboard/app.py`, `run_dev.sh`, `run_prod.sh` removed
- [x] Stock universe in `config/instruments.py` (91 stocks, 18 sectors) and `/api/universe`
- [x] `seed_dashboard_data.py` uses the correct `candle_patterns` name
- [x] WebSocket auto-reconnect with exponential back-off (`upstox_feed.py`)
- [x] Database: Postgres via SQLAlchemy + Alembic migrations (`db/`, `alembic/`)
- [x] Scheduler: APScheduler jobs for news, signals, alerts and backfill (`scheduler/`)
- [x] Dashboard pages: Dashboard, Chart, Positions, Trades, Strategies, Backtest, Daily P&L, News, Signals, Copilot, Watchlists, Alerts, Portfolio Risk, Intraday Lab, Docs
- [x] Paper performance by strategy on the dashboard (Strategies page) and `strategy_report.py`
- [x] `main.py` saves open positions to `data/live_positions.json` on every open/close (and every 5 s) and restores them after a crash. Only its own file, in the same mode, is restored; intraday positions from an earlier day are dropped. Live positions show on the dashboard. Tests: `tests/test_bot_state_persistence.py`
- [x] Live reconciliation against Upstox positions + holdings (`execution_engine/reconcile.py`): at startup and every `execution.reconcile_interval_sec`. Positions the broker does not back are shrunk to what it holds (immediately at startup, after two checks in a row during the session); today's broker positions the bot does not track are alerted. API errors never change the book. Tests: `tests/test_reconcile.py`
- [x] Tick sanity check in `main.py`: ticks ≤ 0 or moving more than `execution.max_tick_jump_pct` (20%) are dropped before stops and strategies see them; a new level is accepted after 3 consistent ticks

---

## 3. Remaining work

### Trading and execution

- [ ] Pair trading: place both legs atomically
- [ ] Options strategies (iron condor, gamma scalping, theta decay, straddle, expiry day): not in `MetaStrategyEngine`; they need a live IV surface, strike/expiry selection and multi-leg P&L tracking
- [ ] PEAD strategy: no earnings-surprise data feed; not in the engine
- [ ] Stock-level delivery % signal: `FIIDIIStrategy.get_stock_delivery_signal()` and `get_size_multiplier()` exist but nothing calls them (the strategy only fires for indices)
- [ ] `beta_neutral.py` hedging: `PortfolioManager` never calls it
- [ ] Factor model (`analytics/factor_model.py`): exposures not shown on the dashboard or in reports
- [ ] Dashboard: no way to place a paper order from the UI
- [ ] Chart page: no live last-price line during market hours

### Data and ML

- [x] ML training and prediction share one feature/dataset definition (`ml_models/dataset.py`); the model's saved `feature_cols` are used at prediction time
- [x] Honest evaluation: per-symbol time split with a 5-bar gap, reported against two naive baselines (always the most common class; always the more common move)
- [x] `train_ml.py --enable` adds `ml_classifier` to `strategies.enabled`, only if the model beats both baselines; a model that doesn't is not saved (`--save-anyway` to override)
- [x] Weekly retraining job (`scheduler.ml_retrain_*`, Sundays 06:00 IST): replaces `models/ensemble.pkl` only if the new model beats the baselines, never enables the strategy
- [ ] **ML model with a real edge.** Trained 2026-10-09 on 10 large caps × 2 years of daily bars, 51 features: 40.9% out-of-sample accuracy vs 48.7% for always predicting "sell"; buy/sell calls right 41.0% vs 48.7%. No model saved, `ml_classifier` stays disabled. Options: intraday bars, other labels/horizons, new features (news, flows) — judged on the same out-of-sample gate
- [ ] `train_ml.py` fetches raw candles itself and skips `UpstoxDataEngine`'s corporate-action adjustment, so splits (e.g. KOTAKBANK) can distort labels
- [ ] Online-learning drift detector (`PageHinkleyDetector`) is not connected to a retraining loop
- [ ] Reinforcement learning agent is a skeleton only
- [ ] Automated pair discovery across the universe (correlation + cointegration scan)
- [ ] Earnings calendar / NSE announcements scraper
- [ ] FII/DII scrape scheduled after NSE publishes (~17:30 IST)
- [ ] Intraday 5m/15m data: Upstox returns HTTP 400 for these intervals on this account; the intraday track defaults to 30m
- [ ] Regime detector still has 5 regimes; no BREAKOUT / MEAN_REVERTING / CRISIS states

### Infrastructure and tests

- [ ] Split `requirements.txt` into prod and dev (`tensorflow`, `pytest`, `stable-baselines3` optional)
- [ ] `yfinance` is used by `advanced_features.py` for cross-asset features but is not in `requirements.txt`
- [x] Tests for the training pipeline, `EnsembleModel` and `train_ml.py` (`tests/test_ml_pipeline.py`); `ModelTrainer` (main.py's fallback trainer) is still only covered indirectly
- [ ] `loony.sh status` hardcodes port 8000
- [ ] Walk-forward optimisation pipeline (Bayesian optimisation → backtest → deploy)
- [ ] Execution quality report (slippage vs VWAP)
- [ ] Systemd service / cloud deployment

---

## 4. Bugs found in the code

Found in the 2026-10-09 audit. All fixed the same day, with regression tests in
`tests/test_bot_position_safety.py`, `tests/test_token_expiry.py`,
`tests/test_backtester.py` and `tests/test_upstox_executor.py`.

- [x] **MIS squareoff left stale positions in `RiskManager` (live mode).** After the broker squareoff, a later stop-loss sent an opposite order on an already-flat position and opened a new, unmanaged one. `main.py` `_squareoff_mis()` now removes squared-off positions from the risk book without sending a second order.
- [x] **MIS squareoff did nothing in `main.py` paper mode.** Tracked paper positions are now closed through simulated fills.
- [x] **New entries were taken after 3:14 PM.** `_on_tick` no longer opens intraday positions after the cut-off. The squareoff flag now resets each trading day instead of firing only once per process.
- [x] **No duplicate / opposite position guard.** A same-direction signal on an open symbol is ignored. An opposite signal closes the position and stays flat instead of flipping. `RiskManager.validate_signal()` also rejects a second position in a symbol.
- [x] **Token expiry computed as 23 h from issue.** New `token_expires_at()` / `token_hours_left()` in `data_engine/upstox/auth.py` use the real 03:30 IST expiry. `main.py`, `check_token.py`, `health.py`, `status.py`, the other scripts and the dashboard routers all use them.
- [x] **`exchanges.upstox.default_product` was ignored.** The executor only read `execution.upstox_product`, so orders were always CNC and setting MIS did nothing. The documented key is now read (`execution.upstox_product` still overrides it).
- [x] **ML model check looked for the wrong files.** `_check_ml_models()` now checks `models/ensemble.pkl` (or `xgboost.pkl` + `lightgbm.pkl`). `_train_or_load_models()` keeps the ensemble the engine already loaded instead of replacing it.
- [x] **`BaseModel.model_dir` was relative to the working directory.** Now anchored to the project's `models/`.
- [x] **8 tests failed on Python 3.12+** (`asyncio.get_event_loop()` outside a loop). Tests use `asyncio.run()`; `main.py` and the executor use `get_running_loop()`.
- [x] **Only the first 5 equity symbols got intraday data** in `main.py`. All equity symbols are seeded now, with a short pause between requests.
- [x] **Backtest warmup was inconsistent** (dashboard API and seed script forced 50, config says 200). The API now uses the configured `warmup_bars` and fetches that much extra history before the requested window. Walk-forward splits borrow their warmup from the preceding bars instead of being skipped.
- [x] **Dashboard backtest map used the old `candlestick_pattern` name.** `candle_patterns` added (old name kept as an alias).
- [x] **`PEADStrategy` and `ExpiryDayStrategy` had no `name`.** Now `pead` and `expiry_day`; they are still not registered in the engine (see §3).
- [x] **`dashboard.port: 8501` was stale.** Set to 8000.
- [x] **ML strategy could never fire.** Training used `advanced_build()` features, prediction used `build()` without the saved column list; every prediction raised and the strategy's blanket `except` returned `None` silently. Fixed via `ml_models/dataset.py`; failures are now logged once.
- [x] **`make_labels` marked the last 5 bars "hold"** instead of unknown (a NaN comparison is False), so they were trained on as holds. Now NaN and dropped.
- [x] **ML "out-of-sample" accuracy was not out of sample.** The 80/20 split ran over symbols concatenated end to end, so the test set was the last two stocks over the same dates. Now split by time within each symbol.
- [x] **`BaseMLModel.predict_proba` default indexed class `p + 1`** (out of range for class 2).
- [x] **Ungated training paths.** `main.py --mode train` trained on one stock with no out-of-sample check, and the bot trained and saved its own model at startup whenever none existed. `--mode train` now runs the gated `retrain()`; startup only loads saved models.
- [x] **10 hardcoded ISINs were stale**, so Upstox returned no data at all for KOTAKBANK, CANBK, BAJFINANCE, SHRIRAMFIN, COFORGE, EICHERMOT, DRREDDY, HAL, HPCL and PAGEIND (charts, signals, backtests, orders). Updated in `config/instruments.py` and the three duplicate maps; verified against live candle data. `tests/test_instrument_isins.py` checks the registry against the Upstox master file and the copies against the registry.

## 5. Documentation problems

Fixed in this pass:

- [x] Removed outdated `todo.md`, `todo/` and `known_issues.md` (merged into this file)
- [x] `quickstart.md`: Docker port 8501 → 8000, test count, full dashboard page list
- [x] `testing.md`: test count and new test files
- [x] `configuration.md`: wrong strategy names (`multi_timeframe_trend`, `support_resistance`, `fii_dii_flow`), options/PEAD marked as not wired, current `enabled` list
- [x] `features.md`: full dashboard page list
- [x] `README.md`: link to this file instead of `known_issues.md`

Still open:

- [ ] `features.md` and `strategies.md` code samples use APIs that do not match the code (e.g. `MetaStrategyEngine(config=...)`, `engine.generate_signal(df, symbol=...)`, `exec.place_order(symbol=..., side=...)`). Check each sample against the code before relying on it.
- [ ] `todo/ROADMAP.md` (repo root, outside `docs/`) marks phases "✅ DONE" while every sub-item is still unticked.

---

## 6. Strategy status

Ticked = registered in `MetaStrategyEngine` and able to fire. "Enabled" = in `strategies.enabled` in `settings.yaml` today.

- [x] `vwap_reversion` — mean reversion · enabled
- [x] `bollinger_reversion` — mean reversion · enabled
- [x] `zscore_reversion` — mean reversion · enabled
- [x] `rsi_mean_reversion` — mean reversion · disabled (negative backtest Sharpe)
- [x] `donchian_breakout` — trend · enabled
- [x] `ema_crossover` — trend · disabled (negative Sharpe)
- [x] `supertrend` — trend · disabled (0 trades on daily bars)
- [x] `mtf_trend` — trend · disabled (needs multi-timeframe frames)
- [x] `sr_breakout` — breakout · disabled (negative Sharpe)
- [x] `breakout_atr` — breakout · disabled
- [x] `range_breakout` — breakout (ORB) · disabled (negative Sharpe)
- [x] `rsi_momentum` — momentum · enabled
- [x] `volume_momentum` — momentum · enabled
- [x] `macd_momentum` — momentum · disabled (negative Sharpe)
- [x] `candle_patterns` — price action · enabled
- [x] `order_book_imbalance` — microstructure · disabled
- [x] `anchored_vwap` — microstructure · enabled
- [x] `cumulative_delta` — microstructure · enabled
- [x] `volume_profile` — microstructure · enabled
- [x] `vix_strategy` — volatility · enabled (NIFTY/BANKNIFTY only)
- [x] `gift_nifty_gap` — gap · enabled (market open only)
- [x] `fii_dii` — institutional · enabled (NIFTY/BANKNIFTY only)
- [x] `pair_trading` — stat arb · runs as a side-car outside the enabled list
- [ ] `ml_classifier` — ML · registered; latest training did not beat the baselines, so no model and not enabled
- [ ] `iron_condor` — options · not in engine
- [ ] `gamma_scalping` — options · not in engine
- [ ] `theta_decay` — options · not in engine
- [ ] `straddle_strangle` — options · not in engine
- [ ] `expiry_day` (`ExpiryDayStrategy`) — options · not in engine
- [ ] `pead` (`PEADStrategy`) — corporate · not in engine, no earnings feed
- [ ] stock delivery % signal (`FIIDIIStrategy.get_stock_delivery_signal()`) — institutional · never called
