# Implementation Status & Open Issues

Single checklist for what is built, what is still to do, and the bugs found in the
code. It replaces the old `todo.md`, `todo/` (P1–P4 gap audit) and `known_issues.md`.

**Last verified against the code:** 2026-10-09 (commit `3fd55bd`).
Offline test suite at that point: **467 tests, 459 pass, 8 fail** (see [Bugs](#4-bugs-found-in-the-code)).

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

---

## 3. Remaining work

### Trading and execution

- [ ] Position state persistence for `main.py` (live mode). Only `paper_trade.py` saves and restores `live_positions.json`; a crash in live mode still loses `RiskManager` positions
- [ ] Portfolio reconciliation against the Upstox positions / holdings API
- [ ] Pair trading: place both legs atomically
- [ ] Options strategies (iron condor, gamma scalping, theta decay, straddle, expiry day): not in `MetaStrategyEngine`; they need a live IV surface, strike/expiry selection and multi-leg P&L tracking
- [ ] PEAD strategy: no earnings-surprise data feed; not in the engine
- [ ] Stock-level delivery % signal: `FIIDIIStrategy.get_stock_delivery_signal()` and `get_size_multiplier()` exist but nothing calls them (the strategy only fires for indices)
- [ ] `beta_neutral.py` hedging: `PortfolioManager` never calls it
- [ ] Factor model (`analytics/factor_model.py`): exposures not shown on the dashboard or in reports
- [ ] Dashboard: no way to place a paper order from the UI
- [ ] Chart page: no live last-price line during market hours

### Data and ML

- [ ] Train and ship ML models. `models/` only contains `hmm/`; `ml_classifier` is also not in the `enabled` list, so ML signals never fire
- [ ] `train_ml.py` should add `ml_classifier` to `strategies.enabled` after training
- [ ] Weekly retraining job (cron or scheduler)
- [ ] Online-learning drift detector (`PageHinkleyDetector`) is not connected to a retraining loop
- [ ] Reinforcement learning agent is a skeleton only
- [ ] Automated pair discovery across the universe (correlation + cointegration scan)
- [ ] Earnings calendar / NSE announcements scraper
- [ ] FII/DII scrape scheduled after NSE publishes (~17:30 IST)
- [ ] Intraday 5m/15m data: Upstox returns HTTP 400 for these intervals on this account; the intraday track defaults to 30m
- [ ] Price sanity check on ticks (`_validate_tick()`: drop LTP ≤ 0 or >20% jumps) — proposed in P4-2, never added
- [ ] Regime detector still has 5 regimes; no BREAKOUT / MEAN_REVERTING / CRISIS states

### Infrastructure and tests

- [ ] Split `requirements.txt` into prod and dev (`tensorflow`, `pytest`, `stable-baselines3` optional)
- [ ] `yfinance` is used by `advanced_features.py` for cross-asset features but is not in `requirements.txt`
- [ ] Tests for `ModelTrainer`, `EnsembleModel` and `train_ml.py`
- [ ] `loony.sh status` hardcodes port 8000
- [ ] Walk-forward optimisation pipeline (Bayesian optimisation → backtest → deploy)
- [ ] Execution quality report (slippage vs VWAP)
- [ ] Systemd service / cloud deployment

---

## 4. Bugs found in the code

Ordered by impact.

- [ ] **MIS squareoff leaves stale positions in `RiskManager` (live mode).** `main.py` `_on_tick` fires `squareoff_all_mis()` but never removes those positions from `risk_manager.positions`. Later stop-loss / take-profit hits call `executor.close_position()` on positions the broker already closed, which sends an order in the opposite direction and opens a new, unmanaged position.
- [ ] **MIS squareoff does nothing in `main.py` paper mode.** `squareoff_all_mis()` returns immediately when `paper=True` ("caller handles virtual positions"), but `main.py` does not close its virtual positions. Paper MIS positions stay open overnight.
- [ ] **New entries are still taken after 3:14 PM.** After the squareoff flag is set, `_on_tick` keeps calling `execute_signal()`, so the bot can open fresh MIS positions between 15:14 and 15:30 that the broker will force-close.
- [ ] **No duplicate / opposite position guard.** `RiskManager.validate_signal()` only checks the concurrent-trade cap, daily drawdown and confidence. Repeated BUY signals on the same symbol stack new positions, and a SELL signal while long opens a short instead of closing the long.
- [ ] **Token expiry is computed from age, not the real expiry.** Upstox tokens expire at 03:30 IST the next day, but `main.py`, `check_token.py` and `health.py` treat a token as valid for 23 h from `obtained_at`. A token obtained at 09:00 is reported valid until 08:00 next day while it actually died at 03:30.
- [ ] **ML model check looks for the wrong files.** `main.py` `_check_ml_models()` looks for `models/{SYMBOL}_ensemble.pkl`, but `train_ml.py` writes, and `MetaStrategyEngine` loads, `models/ensemble.pkl`. The warning fires even when a model exists. `main.py _train_or_load_models()` uses a third path (`models/xgboost.pkl` + `models/lightgbm.pkl` via `BaseModel.save()`).
- [ ] **`BaseModel.model_dir` is relative to the working directory** (`Path("models")`), so models are saved/loaded in the wrong place when a script is run from another directory.
- [ ] **8 tests fail on Python 3.12+.** `tests/test_upstox_executor.py` calls `asyncio.get_event_loop()` outside a running loop, which now raises `RuntimeError`. Use `asyncio.run()` instead. `main.py:208` also uses the deprecated `asyncio.get_event_loop()` inside a coroutine (should be `get_running_loop()`).
- [ ] **Only the first 5 equity symbols get intraday data** in `main.py` `_load_historical_data()`. Every other symbol is scored against the daily cache, which is never refreshed during the session.
- [ ] **Backtest warmup is inconsistent.** `settings.yaml` sets `warmup_bars: 200`, but the dashboard backtest router (`routers/backtest.py:65`) and `seed_dashboard_data.py` force `50`.
- [ ] **`PEADStrategy` and `ExpiryDayStrategy` define no `name`,** so they cannot be enabled by name even if added to the engine.
- [ ] **`dashboard.port: 8501` in `settings.yaml` is stale.** The dashboard runs on 8000 (API) / 5163 (Vite dev).

---

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
- [ ] `ml_classifier` — ML · registered but no trained model and not enabled
- [ ] `iron_condor` — options · not in engine
- [ ] `gamma_scalping` — options · not in engine
- [ ] `theta_decay` — options · not in engine
- [ ] `straddle_strangle` — options · not in engine
- [ ] `expiry_day` (`ExpiryDayStrategy`) — options · not in engine, no `name`
- [ ] `pead` (`PEADStrategy`) — corporate · not in engine, no earnings feed, no `name`
- [ ] stock delivery % signal (`FIIDIIStrategy.get_stock_delivery_signal()`) — institutional · never called
