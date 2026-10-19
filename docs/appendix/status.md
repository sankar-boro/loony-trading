# Project Status

One checklist for what is built, what is still to do, and every bug found in
the code. `[x]` = done and verified in code · `[ ]` = open.

**Last verified against the code:** 2026-10-12. Offline test suite: all passing
(run `pytest tests/ -q --ignore=tests/test_live_upstox.py`).

## Contents

- [1. Done — gap audit (P1–P4)](#1-done--gap-audit-p1p4)
- [2. Done — other implemented work](#2-done--other-implemented-work)
- [3. Remaining work](#3-remaining-work)
- [4. Bugs found and fixed](#4-bugs-found-and-fixed)
- [5. Documentation](#5-documentation)
- [6. Strategy status](#6-strategy-status)

## 1. Done — gap audit (P1–P4)

### P1 · Critical (before the first live trade)

- [x] Daily token renewal script `scripts/auto_login.sh` (cron entry documented)
- [x] Token expiry check at bot startup (blocks live mode, warns in paper mode)
- [x] MIS squareoff at 15:14 IST in `paper_trade.py` and `main.py`
- [x] Paper trader state saved to `data/live_positions.json` every tick and restored on restart (< 1 h old)
- [x] Market-hours guard in `paper_trade.py`, `live_signals.py`, `market_watch.py` and `main.py`

### P2 · Trading correctness

- [x] Split/bonus price adjustment (`data_engine/upstox/corporate_actions.py`, applied in `fetch_ohlcv()`)
- [x] Itemised NSE charges in paper fills (MIS ≈ 0.055 %, CNC ≈ 0.21 % round trip)
- [x] Backtester uses `commission_intraday` / `commission_delivery`
- [x] Intraday data refresh in `paper_trade.py`
- [x] Options key resolver, multi-leg `place_basket_order()`
- [x] F&O lot sizes snapped before every order

### P3 · Observability

- [x] Telegram alerts in `paper_trade.py`, `live_signals.py`; `main.py` notifies through `Notifier`
- [x] End-of-day report → `data/daily_pnl.jsonl` + Telegram summary; `scripts/daily_report.py`
- [x] `scripts/trade_journal.py` (by strategy / symbol / date, CSV export)
- [x] Benchmark comparison (alpha, beta, information ratio vs Nifty 50) in backtests

### P4 · Infrastructure

- [x] NSE holidays fetched and cached (`data/nse_holidays.json`); `india_market.holidays` used as the offline fallback
- [x] Protobuf decoder check in `upstox_feed.py`
- [x] Streamlit dashboard replaced by FastAPI + React
- [x] Equity curve file and dashboard chart
- [x] `scripts/tune_weights.py`

### Intraday audit ([Intraday Readiness Audit](intraday-audit.md))

- [x] Live tick loop refreshes strategy data from live bars (`data_engine/live_bars.py`)
- [x] Session-anchored VWAP and anchored VWAP
- [x] Opening range breakout anchored to the 09:15 IST open
- [x] Backtester simulates the MIS squareoff
- [x] Order HTTP calls off the event loop
- [x] Timeframe-aware composite signals and alerts
- [x] Opt-in intraday scheduler track

## 2. Done — other implemented work

- [x] Docker Compose with Postgres, Redis, dashboard (port 8000, single worker) and bot; healthchecks
- [x] `.env.example`; `requirements.txt` without Streamlit (heavy ML packages optional)
- [x] Stock universe of 91 stocks in 18 sectors (`config/instruments.py`), `/api/universe`
- [x] Microstructure strategies (anchored VWAP, cumulative delta, volume profile) in the engine
- [x] WebSocket auto-reconnect with exponential back-off
- [x] PostgreSQL via SQLAlchemy + Alembic; APScheduler jobs for news, signals, alerts, analogue backfill and ML retraining
- [x] Dashboard: 16 pages including the Docs reader and the Intraday Desk
- [x] Live-bot position persistence and crash recovery (`tests/test_bot_state_persistence.py`)
- [x] Live reconciliation with Upstox positions + holdings (`execution_engine/reconcile.py`, `tests/test_reconcile.py`)
- [x] Tick sanity check with recovery after a genuine gap
- [x] ML pipeline: shared dataset definition, honest per-symbol time split, out-of-sample gate, gated `--enable`, weekly gated retrain (`tests/test_ml_pipeline.py`)
- [x] One position per symbol; opposite signals close and stay flat
- [x] Unfilled live orders cancelled after the status poll; partial fills tracked at their filled size
- [x] The handbook: 60+ chapters, served by the dashboard with contents and search; `tests/test_docs.py` checks links, anchors and tables
- [x] Handbook copied into Postgres (`doc_chapters`, `doc_sections`) by `scripts/migrate_docs.py`, which runs the table definitions in `db/sql/handbook.sql` and loads `docs/`; `DB_*` connection settings and `DB_SCHEMA` support (`tests/test_docs_sync.py`)
- [x] Deployment documented (Docker Compose, systemd units, security checklist)

### Notifications ([Avoiding noise](../operations/notifications.md#avoiding-noise))

- [x] Shared dedupe + rate limit for both senders; e-mail from WARNING up; scanner signals once a day; alert cooldown per stock (`tests/test_notifications.py`)

### Execution ([Execution](../engine/execution.md))

- [x] Limit-order chasing; execution log (`logs/executions.jsonl`), `scripts/execution_report.py` and the Trades page's Execution quality tab
- [x] GTT orders on the Upstox v3 API; delivery positions' broker stops are GTTs that survive the close (`tests/test_execution_quality.py`)

### Portfolio analytics ([Portfolio Risk](../dashboard/portfolio-risk.md#beta-factors-and-stress-tests))

- [x] Beta and futures hedge suggestion, factor exposures and crisis stress tests for the current holdings (`GET /api/portfolio/analytics`, `tests/test_portfolio_analytics.py`)
- [x] Stress scenarios calibrated to their stated Nifty falls; stress beta scaled to the invested share of capital

### Signal track record ([Did the signals work?](../marketpulse/composite-signals.md#did-the-signals-work))

- [x] `signal_outcomes`: 1/5/20-day returns and setup target/stop/expiry, weekday job and `scripts/evaluate_signals.py`; setups invalidated
- [x] Track record view on the Signals page and `GET /api/signals/performance` (`tests/test_signal_outcomes.py`)

### Regimes ([Market regimes](../engine/strategy-framework.md#market-regimes))

- [x] Gated HMM fitting (`scripts/fit_regimes.py`, opt-in weekly job): must predict near-term volatility out of sample and have persistent regimes; standardised features
- [x] `BREAKOUT` and `CRISIS` regimes; crisis pauses new entries
- [x] Regime and its source on the Chart page (`tests/test_regimes.py`)

### Pair trading ([Pair Trading](../engine/strategies-stat-arb.md))

- [x] Stateless pair evaluation with numpy Engle-Granger test and half-life (statsmodels was never installed, so the old tests were no-ops)
- [x] `scripts/find_pairs.py` and `backtester/pair_backtester.py`
- [x] Live pairs from `strategies.pairs`: both legs together, unwind on a failed leg, spread exits, partner close; MIS only (`tests/test_pair_trading.py`)

### Intraday trading ([Intraday Session Controls](../engine/intraday-controls.md))

- [x] Entry window (09:30–14:45 by default) for new MIS entries
- [x] Daily and per-symbol trade caps; counted on filled entries only
- [x] Cooldown after a stop-out
- [x] Kill switch on realised + unrealised day P&L, which flattens and halts; optional profit lock
- [x] Operator pause / resume / flatten through `data/bot_control.json`, each executed exactly once (`tests/test_bot_intraday.py`)
- [x] Exchange-held SL-M stops (opt-in, live), trailed with the stop; checked or cancelled before every close so the stop and the close can never both fill
- [x] Feed heartbeat alert; bot event log; minute P&L log
- [x] Session state survives a same-day restart
- [x] Live 1-minute bars recorded to `data/live_bars/`; `backtest_runner.py --source recorded`
- [x] Intraday Desk page (`/desk`) and `GET /api/intraday/desk`, `POST /api/intraday/control`
- [x] Backtester: intrabar stop/target fills from high/low (stop first on a tie), gap fills at the open, trailing stop, exit costs at `end_of_data` (`tests/test_backtester_intrabar.py`)

## 3. Remaining work

### Trading and execution

- [ ] **Index signals are not tradable.** `vix_strategy`, `fii_dii` and `gift_nifty_gap` signal on `NIFTY50`/`BANKNIFTY`; the executor has no mapping to futures, options or an ETF, so live index orders would be rejected and paper mode treats the index as a stock
- [ ] Options strategies not in the engine; the options resolver builds name-based keys (`NSE_FO|NIFTY25JUN24500CE`) but real Upstox F&O keys are numeric tokens from the instrument master; F&O STT is not modelled in `_compute_charges()`
- [ ] `ExpiryDayStrategy` assumes weekly BankNifty expiries, which NSE discontinued in 2024
- [ ] `order_book_imbalance` never receives an order book and `mtf_trend` never receives multi-timeframe frames, so neither can fire
- [ ] PEAD has no earnings-surprise source; not in the engine
- [ ] Stock delivery % signal and FII/DII size multipliers exist but are never called
- [ ] Libraries not wired into the bot: CVaR limits, circuit-breaker checks, TWAP/VWAP execution (the kill switch is built in; beta, factors and stress tests are on the Portfolio Risk page, not traded on)
- [ ] Intraday session rules apply to `main.py` only; `scripts/paper_trade.py` has none of them
- [ ] Backtests do not apply the live session rules (entry window, trade caps, cooldown, kill switch)
- [ ] Exchange-held stops are untested against the real Upstox API (unit-tested with fakes); try with one share before relying on them
- [ ] No per-position manual close button on the Intraday Desk (Flatten all only)
- [ ] Positions opened by hand at the broker are alerted, not adopted
- [ ] Paper trader charges a flat 0.1 % per side rather than itemised NSE charges, and closes every position at 15:14 (treats all trades as intraday)
- [ ] Crypto executor (`execution_engine/executor.py`) still retries order placement
- [ ] Dashboard: no paper-order button; Chart drawing tools are visual only; no live price line

### Data, strategies and ML

- [ ] **Re-tune the default strategy list and weights.** The shipped `enabled`/`weights` came from backtests that predate the VWAP fix (on daily bars `vwap_reversion` used to fire on every bar) and the cost fix (costs were double-counted)
- [ ] **GIFT Nifty has no data source** (`NSE_INDEX|GIFT NIFTY` is not in the Upstox master; the fallback reads Nifty's own last price) — `gift_nifty_gap` is enabled but effectively inactive
- [ ] Macro strategies (VIX, FII/DII, GIFT) read today's data and the wall clock, so their backtests are not meaningful
- [ ] Strategy parameters are read from top-level config keys and none are set; consider a `strategies.params` section
- [ ] ML model with a real edge: the 2026-10-09 run reached 40.9 % accuracy vs a 48.7 % baseline (not saved, not enabled). Try intraday bars, other horizons, point-in-time context features
- [ ] `train_ml.py` downloads raw candles and skips the split/bonus adjustment
- [ ] Advanced features attach today's VIX/flow/macro values to every historical row — usable for latest-bar inference only
- [ ] Online drift detector not connected to retraining; RL agent is a skeleton
- [ ] Earnings calendar scraper; automated pair discovery
- [ ] FII/DII scrape scheduled after NSE publishes (~17:30 IST)
- [ ] Upstox returns HTTP 400 for 5/15-minute historical candles on this account (defaults use 30m)
- [ ] BSE lot sizes (SENSEX, BANKEX) in `FO_LOT_SIZES` not re-verified

### Backtesting

- [ ] Position cap is 25 % of capital vs `risk.max_portfolio_risk` (20 %) live

### Dashboard and MarketPulse

- [ ] Price stream `change_pct` is the change since the previous 2-second poll, not since yesterday's close (Home and Chart lists show ~0 %)
- [ ] News cards label `impact_score × 10` as "catalyst"
- [ ] Portfolio Risk "Daily P&L" adds the latest daily record, which is yesterday's until today's report is written
- [ ] The dashboard has no authentication
- [ ] `ANTHROPIC_MODEL` defaults to `claude-opus-5`; `claude-opus-5-5` is newer and cheaper
- [ ] `dashboard/backend/routers/backtest.safe.py` is dead code

### Infrastructure

- [ ] Split `requirements.txt` into runtime and dev (pytest)
- [ ] `logs/trading.log` is relative to the working directory
- [ ] `loony.sh status` hardcodes port 8000
- [ ] Walk-forward optimisation pipeline; execution-quality report
- [ ] `ModelTrainer` only covered indirectly by tests

## 4. Bugs found and fixed

All found in the 2026-10-09 audits and fixed the same day, each with
regression tests.

### Live trading safety

- [x] **A failed live close was booked at ₹0** (2026-10-19): a rejected market close recorded a fake P&L and dropped a position that was still open at the broker — closes are booked only when filled, retried after 30 s
- [x] **MIS squareoff left stale positions** in the risk book (live), so a later stop sent an opposite order on a flat position — now removed without a second order
- [x] **MIS squareoff did nothing in `main.py` paper mode** — paper positions now closed
- [x] **New entries after 15:14** — blocked for MIS; squareoff re-arms each day
- [x] **No duplicate/opposite position guard** — one position per symbol; opposite signals close and stay flat
- [x] **Unfilled live limit orders were left working** at the broker (and partial fills mis-tracked) — cancelled after the status poll; partial fills tracked at their filled size; entry price is the actual fill
- [x] **Order placement was retried**, risking duplicate orders after a timeout — single attempt; reconciliation alerts if a "failed" order actually went through
- [x] **Daily drawdown limit never reset** (`reset_daily()` was never called) — resets on each new IST trading day
- [x] **Live ticks were labelled with raw instrument keys**, so stops were never checked against them and live bars never matched — ticks carry the subscribed symbol
- [x] **Feed tick filter froze a symbol** for the session after a genuine > 20 % gap — removed; the bot's recoverable check applies
- [x] **`exchanges.upstox.default_product` was ignored** (orders always CNC) — now read
- [x] **Strategy weights ignored** by the live bot and the backtester (raw confidence ranking) — all use `best_signal()`

### Tokens, configuration and calendar

- [x] **Token expiry computed as 23 h** across the bot, scripts, dashboard, `auto_login.sh` and the price stream — real 03:30 IST rule everywhere (`token_expires_at()`)
- [x] **`main.py` never loaded `.env`**, so `${UPSTOX_API_KEY}`, Telegram and other settings were empty unless exported — the settings loader now reads `.env`
- [x] **`utils.timeutils` ignored NSE holidays** (paper trader and scanner ran on holidays) and `india_market.holidays` was never read — both fixed
- [x] **`timeframes.intraday: 15m`** fails with HTTP 400 on this account, silently dropping the bot back to daily data — default now `30m`
- [x] **Stale `dashboard.port: 8501`** — set to 8000

### Instruments and lot sizes

- [x] **Instrument master URLs returned 403**, leaving 66 of 99 universe symbols and indices unresolvable — working URLs, and the registry is always seeded from `config/instruments.py`
- [x] **`MIDCAP` resolved to an ETF** of the same ticker — universe symbols take precedence
- [x] **Instrument keys copied across the code base** (2026-10-18): `KNOWN_INSTRUMENTS`, `scripts/order.py`, `scripts/market_watch.py`, `scripts/seed_dashboard_data.py`, `scripts/test_upstox.py`, `scripts/check_token.py`, `scripts/option_chain.py` and the index keys in the VIX, GIFT Nifty, factor-model, beta-hedge, stream and backtest code — all now read `config/instruments.py`; a test fails on any new hardcoded key
- [x] **10 stale ISINs** (KOTAKBANK, CANBK, BAJFINANCE, SHRIRAMFIN, COFORGE, EICHERMOT, DRREDDY, HAL, HPCL, PAGEIND) returned no data — updated; `tests/test_instrument_isins.py`
- [x] **Stale F&O lot sizes** (NIFTY 75→65, FINNIFTY 65→60, MIDCPNIFTY 75→120; beta hedge used 50) — updated, master lot size preferred
- [x] **Lot snapping never applied** to real numeric F&O keys — uses the master's per-contract lot size

### Strategies and backtesting

- [x] **A fresh candle cache from a short request answered longer ones** (2026-10-18), silently truncating backtests, ML training and research to as little as 60 days — the cache is used only if it covers the requested range
- [x] **Backtest stops and targets were checked on bar closes only**, with no trailing stop, so wicks through a stop were missed (2026-10-12) — high/low fills, gaps at the open, trailing stop
- [x] **`end_of_data` exits paid no cost or slippage**, and their P&L was missing from the equity curve (2026-10-12)

- [x] **`vwap_reversion` fired on every daily bar** (zero-width session bands) and `anchored_vwap` on float noise — both require intraday sessions
- [x] **Backtester charged round-trip costs on each leg** (double) — half per side
- [x] **`tune_weights.py` wrote non-existent names** (`multi_tf_trend`, `candlestick_pattern`) and **dropped every strategy it could not backtest** from `enabled` — uses engine names, keeps untested strategies
- [x] **Strategy Lab could not backtest 6 of the 13 enabled strategies** ("Unknown single strategy") — any registered strategy runs through a one-strategy engine
- [x] **Strategies page list was stale** — derived from the engine (`registered_strategy_names()`)
- [x] **Backtest warmup inconsistent** (50 vs 200) and walk-forward splits skipped — config warmup plus extra history; splits warm up on preceding bars
- [x] **`PEADStrategy` / `ExpiryDayStrategy` had no `name`**

### ML

- [x] **ML strategy could never fire** (training/prediction feature mismatch, errors swallowed)
- [x] **Last 5 bars labelled "hold"** instead of unknown
- [x] **"Out-of-sample" split was not out of sample** (split across concatenated symbols)
- [x] **Ungated training paths** (`--mode train`, bot startup) — gated `retrain()` only; startup loads only
- [x] **Model check looked for the wrong files; model dir relative to CWD; `predict_proba` default index off by one**

### Other

- [x] **8 executor tests failed on Python 3.12+** (`asyncio.get_event_loop()`)
- [x] **Only the first 5 equity symbols got intraday data** in the live bot
- [x] **Docker Compose ran 2 backend workers**, which would run every scheduler job twice — 1 worker
- [x] **`HTTPException` not imported** in the SPA fallback route

## 5. Documentation

- [x] The handbook (`docs/book.yaml`) replaces `quickstart.md`, `features.md`, `strategies.md`, `configuration.md`, `testing.md`, `scenarios.md`, `todo.md`, `todo/` and `known_issues.md`; every chapter was written from the code
- [x] Code samples in the old `features.md` / `strategies.md` that did not match the code are gone
- [ ] `todo/ROADMAP.md` (repository root) marks phases "✅ DONE" while their sub-items are unticked — superseded by this page

## 6. Strategy status

Ticked = registered in `MetaStrategyEngine` and able to fire in the bot today.
"Enabled" = in `strategies.enabled` in `settings.yaml`.

- [x] `vwap_reversion` — mean reversion · enabled · intraday bars only
- [x] `bollinger_reversion` — mean reversion · enabled
- [x] `zscore_reversion` — mean reversion · enabled
- [x] `rsi_mean_reversion` — mean reversion · disabled
- [x] `donchian_breakout` — trend · enabled
- [x] `ema_crossover` — trend · disabled
- [x] `supertrend` — trend · disabled
- [ ] `mtf_trend` — trend · disabled · needs `frames=`, never passed
- [x] `sr_breakout` — breakout · disabled
- [x] `breakout_atr` — breakout · disabled
- [x] `range_breakout` — breakout (ORB) · disabled
- [x] `rsi_momentum` — momentum · enabled
- [x] `volume_momentum` — momentum · enabled
- [x] `macd_momentum` — momentum · disabled
- [x] `candle_patterns` — price action · enabled
- [ ] `order_book_imbalance` — microstructure · disabled · needs an order book, never passed
- [x] `anchored_vwap` — microstructure · enabled · intraday bars only
- [x] `cumulative_delta` — microstructure · enabled
- [x] `volume_profile` — microstructure · enabled
- [x] `vix_strategy` — volatility · enabled · indices only
- [ ] `gift_nifty_gap` — gap · enabled · no GIFT Nifty data, effectively inactive
- [x] `fii_dii` — institutional · enabled · indices only
- [ ] `pair_trading` — stat arb · built but never invoked
- [ ] `ml_classifier` — ML · no model passed the gate; not enabled
- [ ] `iron_condor`, `gamma_scalping`, `theta_decay`, `straddle_strangle`, `expiry_day` — options · not in engine
- [ ] `pead` — corporate · not in engine, no earnings feed
