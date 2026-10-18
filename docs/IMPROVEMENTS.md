# Improvements and Extensions

[TODO](TODO.md) lists the open problems. This chapter covers the other
half: code that exists but is unfinished, unconnected, or simpler than it
should be, and how each area could be extended. It is based on an audit of
the code on 2026-10-18. That audit:
- checked which modules production code actually imports;
- read each strategy and service;
- traced what the dashboard calls.

Each area gets one of three labels:

| Label | Meaning |
|---|---|
| **Not wired** | The code is written, but nothing in the bot, dashboard or scheduler calls it |
| **Partial** | Wired in, but missing pieces that stop it working as intended |
| **Basic** | Works, but minimal; the obvious next features are missing |

## Summary

| Area | Status | In one line |
|---|---|---|
| [Short selling in delivery](#short-selling-in-delivery) | **Done** | CNC short entries are refused in the executor, the bot and the backtester |
| [Core strategies](#core-strategies) | Partial | Parameters, setup-based confidence and strategy exits done; ensemble voting and multi-timeframe data still to do |
| [Options, PEAD and expiry strategies](#options-pead-and-expiry-strategies) | Not wired | About 1,550 lines of strategies that never run |
| [Pair trading](#pair-trading) | **Done** | Pair discovery, pair backtester and live trading of both legs as one unit (MIS) |
| [Regime detection](#regime-detection) | **Done** | Gated HMM (fit script and weekly job), breakout and crisis regimes, regime on the Chart page |
| [Features](#features) | Partial | Advanced OI/IV/macro features used only by tests |
| [Risk management](#risk-management) | Basic | Sector cap and per-strategy limits done; CVaR and volatility targeting still to wire |
| [Execution](#execution) | Basic | Market/limit only; the 422-line smart-order router is unused |
| [Portfolio analytics](#portfolio-analytics) | Not wired | Factor model, beta hedge, stress test: about 720 lines, never called |
| [Backtesting](#backtesting) | Basic | One symbol, one position at a time; no portfolio backtest |
| [Machine learning](#machine-learning) | Partial | Ensemble trains; TFT, online learning, RL, Bayesian tuning never used |
| [Composite signals](#composite-signals) | Partial | Scored and stored, but outcomes are never measured |
| [Copilot](#copilot) | Basic | Keyword router plus one LLM call; no conversation or tools |
| [News](#news) | Basic | NewsAPI or demo only |
| [Database](#database) | Partial | `price_bars` table never written; trade setups never invalidated |
| [Notifications](#notifications) | Basic | Telegram and e-mail, no rate limit or routing |
| [Dashboard](#dashboard) | Basic | Read-only settings, polling, no order entry |
| [Paper trading](#paper-trading) | Partial | A second bot that has diverged from `main.py` |

## Short selling in delivery

**Today:** a SELL signal on a flat symbol opens a short position.
`UpstoxExecutor.execute_signal` sends a SELL order whatever the product, and
the default product is `CNC` (delivery). NSE does not allow an overnight
short in the cash segment: Upstox rejects the order, or a short that slips
through ends in an exchange auction with a penalty. Paper mode and the
backtester simulate these shorts happily, so their results include trades
the live bot cannot make.

**Done (2026-10-18):** on CNC a SELL now only closes a long. New shorts
need MIS or NRML (`risk_manager.can_open_short()`), enforced in the executor
(live and paper), the bot (logged as a `block` event) and the backtester. See
[Shorts need MIS](engine/execution.md#shorts-need-mis).

**Still to extend:**
- Route bearish views to futures or puts once
  [options are wired in](#options-pead-and-expiry-strategies).
- Add a `direction` setting per strategy: long-only, short-only or both.

## Core strategies

**Today:** `MetaStrategyEngine` registers 19 core strategies plus three
data-dependent ones (VIX, GIFT Nifty gap, FII/DII) and the ML classifier.
Most core strategies are 40–60 lines. For example, `rsi_momentum` buys when
RSI(14) crosses 50 above the 50-period EMA.
- Indicator periods are hard-coded.
- Every signal carries a constant confidence (0.65).
- Stops and targets come from one shared ATR rule.

The best signal is chosen by confidence × weight. With constant confidences
that is effectively a fixed priority order, not a judgement of signal
quality.

**Done (2026-10-18):**
- [Parameters](engine/strategy-framework.md#where-parameters-come-from)
  under `strategies.params.<name>`, including stop/target ATR multiples and
  a time stop for every strategy, shown on the Strategies page.
- Setup-based confidence (`scaled_confidence`) for the six strategies that
  used a constant: `donchian_breakout`, `supertrend`, `vwap_reversion`,
  `volume_momentum`, `rsi_momentum`, `range_breakout`.
- [Strategy exits](engine/strategy-framework.md#strategy-exits)
  (`should_exit`) in the live bot and the backtester. Rules are written for
  `donchian_breakout`, `supertrend`, `ema_crossover`, `rsi_momentum` and
  `zscore_reversion`, plus a time stop for all.

**Gaps:**
- No partial profit-taking.
- `order_book_imbalance` never receives an order book and `mtf_trend` never
  receives multi-timeframe frames, so both can never fire.
- Exit rules for the remaining strategies.

**Extend with:**
- Subscribe the live feed in `full` mode (it supports it, but defaults to
  `ltpc` and only parses LTPC messages), decode the market depth, and pass
  it to `order_book_imbalance`.
- Build multi-timeframe frames from the recorded 1-minute bars for
  `mtf_trend`.
- Ensemble voting: require two strategies to agree, or score the agreement
  across all of them.

## Options, PEAD and expiry strategies

**Not wired:**

| Module | Lines | What it does |
|---|---|---|
| `strategies/options/gamma_scalping.py` | 220 | Long-gamma scalping |
| `strategies/options/iron_condor.py` | 221 | Range-bound premium selling |
| `strategies/options/straddle_strangle.py` | 208 | Volatility plays |
| `strategies/options/theta_decay.py` | 183 | Premium decay |
| `strategies/options/expiry_strategy.py` | 370 | Expiry-day setups; assumes weekly BankNifty expiries, which NSE ended in 2024 |
| `strategies/corporate/pead_strategy.py` | 354 | Post-earnings drift; has no earnings data source |

The options strategies sit next to useful plumbing: an IV surface
(`data_engine/upstox/iv_surface.py`), Greeks (`feature_engine/greeks.py`)
and a multi-leg `place_basket_order()`. But the options resolver builds keys
like `NSE_FO|NIFTY25JUN24500CE`, while real Upstox F&O keys are numeric
tokens from the instrument master.

**To wire them in:**
1. Resolve option contracts from the instrument master: underlying, expiry,
   strike, type → numeric key, lot size.
2. Add a multi-leg position type to `RiskManager`: a strategy as one unit,
   with combined P&L, margin and Greeks.
3. Model F&O charges (STT on premium and on exercise) in the cost model.
4. Register the options strategies in the engine behind their own
   `enabled` list, paper-only at first.
5. Update `ExpiryDayStrategy` to the current NSE expiry calendar.
6. Give PEAD an earnings source (an NSE corporate announcements scraper)
   and register it.

## Pair trading

**Done (2026-10-18):** see [Pair Trading](engine/strategies-stat-arb.md).
- The strategy is stateless: an OLS (or calibrated Kalman) hedge ratio,
  z-score, Engle-Granger test and half-life over a lookback window. Pairs
  that fail the tests are no longer traded "with caution". The tests were
  silently no-ops before, because they needed statsmodels, which is not
  installed. They are now plain numpy.
- `scripts/find_pairs.py` scans same-sector pairs, and
  `backtester/pair_backtester.py` backtests both legs together.
- The live bot trades `strategies.pairs` as one unit: legs opened and
  closed together, an unwind if the second leg fails, spread exits, and
  partner close if one leg stops out. MIS only.

**Still to extend:**
- Overnight pairs through futures, once F&O contracts resolve.
- A pair-spread chart on the Chart page.
- Both legs in one basket order.

## Regime detection

**Done (2026-10-18):** see [Market regimes](engine/strategy-framework.md#market-regimes).
- `scripts/fit_regimes.py`, plus an opt-in weekly `regime_refit` job. An
  out-of-sample gate requires each model to predict near-term volatility
  and to have persistent regimes; failing models are never used.
- Features are standardised before fitting. With raw features the fit
  could diverge to NaN, for example for an index whose volume is always
  zero, and return variance sat below hmmlearn's variance floor.
- `BREAKOUT` and `CRISIS` regimes. In a crisis only strategies tagged
  `crisis` trade, so new entries pause.
- The HMM decides calm versus turbulent, and the ADX rules decide trend
  inside calm markets.
- The regime and its source are on the Chart page.
- Fixed along the way: a fresh candle cache from a short request was
  returned for a longer one, silently truncating backtests and training
  data.

**Still to extend:**
- Features that let the HMM find trends itself (longer-window returns).
- Per-strategy results by regime, to check that the regime filters help.

## Features

**Today:** `FeatureBuilder` (indicators) feeds the strategies and ML, and
`CandlestickPatternStrategy` uses the pattern detector.
`feature_engine/advanced_features.py` (325 lines) computes open-interest,
IV, flow and macro features, but only tests call it. Its macro features also
attach *today's* values to every historical row, so they would leak future
data into training.

**Extend with:**
- Daily snapshots of OI, IV, FII/DII and VIX, so features can use the value
  as it was on each date.
- Plugging the point-in-time features into `FeatureBuilder` behind a flag,
  and into ML training.
- Relative-strength features: stock against its sector index and Nifty.

## Risk management

**Today:** `RiskManager` sizes each trade to risk 1 % of capital over the
stop distance (optional fractional Kelly), caps concurrent positions,
trails stops, and blocks new trades after the daily loss limit. The
intraday guard adds the session rules and the kill switch. The bot skips a
symbol highly correlated with an open position.

**Done (2026-10-18):**
- [Sector exposure cap](engine/risk-management.md#sector-exposure-cap)
  (`risk.max_sector_exposure`, 30 %). Entries are trimmed to fit and
  blocked when the sector is full.
- [Per-strategy loss limits](engine/intraday-controls.md#strategy-limits).
  A strategy is switched off for the day after a daily loss or a losing
  streak; this shows on the Intraday Desk, and Resume re-enables it. They
  replace the unconnected `analytics/live_pnl.py`, which was removed.
- Orders sized below one lot are skipped instead of rounded up to a lot.

**Not wired:**
- `risk_manager/cvar.py` (261 lines): CVaR / expected-shortfall limits.

**Gaps:**
- No capital allocation per strategy.
- No volatility targeting: position size ignores how volatile the stock is,
  beyond the stop distance.
- No check of available margin or funds before ordering.

**Extend with:**
- A portfolio CVaR check before each entry.
- Halving a strategy's size after a shorter losing streak, before switching
  it off.
- A funds check through the Upstox funds API before live orders.

## Execution

**Today:** `UpstoxExecutor` places market or limit orders (`smart` picks
market above 0.85 confidence). It polls fills for 30 s, cancels unfilled
orders, tracks partial fills and never retries. Exchange-held SL-M stops are
optional.

**Not wired:** `execution_engine/smart_order.py` (422 lines) has TWAP/VWAP
slicing and an Indian intraday volume profile.

**Extend with:**
- Limit-order chasing: re-price an unfilled limit order toward the market a
  few times before cancelling.
- TWAP/VWAP slicing for orders above a size threshold, using `smart_order`.
- Upstox GTT orders, so delivery positions keep stops across days.
- An execution-quality report: slippage per order against the signal price
  and arrival price, per strategy and time of day.

## Portfolio analytics

**Not wired:**

| Module | Lines | What it does |
|---|---|---|
| `analytics/factor_model.py` | 232 | Exposure to market, banking, IT, FMCG, auto and midcap index factors |
| `portfolio_manager/beta_neutral.py` | 219 | Nifty futures hedge to neutralise portfolio beta |
| `backtester/stress_test.py` | 268 | Replays five Indian crises against a strategy's returns |

**Extend with:**
- Factor exposures and a stress-test table on the Portfolio Risk page.
- A "hedge" suggestion from `beta_neutral` on the same page, and later an
  optional automatic hedge in live mode.
- A stress test after every backtest in the Strategy Lab.

## Backtesting

**Today:** the backtester is realistic for one symbol at a time:
- high/low stop fills and gaps;
- the trailing stop and per-side costs;
- MIS squareoff;
- walk-forward splits and Monte Carlo.

**Gaps:**
- One position at a time, one symbol per run. There is no portfolio
  backtest with shared capital, concurrent positions, correlation guard and
  sector exposure, which is how the bot actually trades.
- No session rules (entry window, caps, cooldown, kill switch).
- No parameter optimisation: `ml_models/bayesian_opt.py` (307 lines) exists
  but is unused.
- Results are not saved; each run is lost after the page closes.

**Extend with:**
- A portfolio backtester that replays many symbols bar by bar through the
  same `RiskManager` and `IntradayGuard` the bot uses.
- Walk-forward optimisation with `bayesian_opt`, scored out of sample.
- Saving runs (parameters, metrics, trades) to the database, with a
  compare-runs view in the Strategy Lab.
- A benchmark and buy-and-hold line on every equity curve.

## Machine learning

**Today:** `scripts/train_ml.py` builds a dataset, trains an ensemble
(XGBoost, LightGBM, optionally LSTM through `ModelTrainer`), and saves it
only if it beats naive baselines out of sample. The last run did not.

**Not wired:**

| Module | Lines | State |
|---|---|---|
| `ml_models/tft_model.py` | 251 | Temporal Fusion Transformer; never trained or loaded |
| `ml_models/online_model.py` | 332 | Online learning and drift detection; not connected to retraining |
| `ml_models/rl_agent.py` | 140 | A trading environment and agent skeleton |
| `ml_models/bayesian_opt.py` | 307 | Hyper-parameter search; unused |

**Extend with:**
- Better targets than next-bar direction: returns over several bars,
  barrier labels (target before stop), or meta-labelling of the rule
  strategies' own signals.
- Training on intraday bars from the recorder.
- Point-in-time context features (see [Features](#features)).
- Connecting the drift detector, so drift triggers the gated retrain early.
- Model metrics and feature importance on a dashboard page.

## Composite signals

**Today:** the signal engine scores every stock from seven components
(catalyst, technical, momentum, volume, historical, regime, risk) and stores
a `Signal` and a `TradeSetup` with entry zone, stop and targets.

**Gaps:**
- Nobody checks whether signals worked. There are no forward returns, hit
  rates or results per component.
- `TradeSetup.invalidated_at` is never set, so stale setups look live
  forever.
- Component weights are fixed in config, never fitted.

**Extend with:**
- A daily job that records each signal's 1/5/20-day returns and whether the
  setup hit target or stop first.
- A signal-performance page: hit rate by direction, score band and
  component.
- Weights fitted to those outcomes, with the same out-of-sample gate the ML
  model uses.
- Invalidating setups when price closes beyond the stop or the entry zone
  passes.

## Copilot

**Today:** a deterministic keyword router picks what data to fetch, then one
structured LLM call writes the answer with citations. The code calls the
router "intentionally narrow".

**Extend with:**
- Tool use: let the model call `get_signals`, `get_news`, `why_is_it_moving`
  and `get_positions` itself instead of keyword routing.
- Conversation memory per session.
- Questions about your own book ("why did the bot exit TCS?"), using the
  bot's events and trade log.
- Streaming answers on the Copilot page.

## News

**Today:** two providers, NewsAPI.org and a demo provider. News is
classified (LLM or demo), matched to stocks by
`data_engine/news/entity_resolution.py`, and turned into events.

**Extend with:**
- NSE/BSE corporate announcements, the most price-relevant source for
  Indian stocks, and free.
- RSS feeds from Indian financial outlets.
- De-duplicating the same story across sources.
- Sentiment as a time series per stock, charted under the price.

## Database

**Partial:**
- The `price_bars` table is defined and migrated but never written; candles
  live in parquet files under `data/cache/`.
- `trade_setups.invalidated_at` is never set (see
  [Composite signals](#composite-signals)).

**Extend with:**
- Either store candles in `price_bars` (one place for the dashboard,
  backtests and ML) or drop the table.
- Bot trades, events and the minute P&L in the database instead of JSONL
  files, so the dashboard can query history.
- A retention job for `signals` and `alert_triggers`.

## Notifications

**Today:** `Notifier` sends to Telegram and e-mail.

**Extend with:**
- Rate limiting and de-duplication: the same message at most once per N
  minutes.
- Severity routing: kill switch and errors to every channel, entries and
  exits to Telegram only.
- Telegram commands (`/status`, `/pause`, `/flatten`) using the same
  control file as the Intraday Desk.
- Slack or webhook channels.

## Dashboard

**Today:** 16 pages. Everything is read-only except the Intraday Desk
controls, watchlists, alerts and backtests.

**Extend with:**
- **Settings page:**
  - edit strategy enable/weights, risk limits and intraday rules, writing
    `settings.yaml`;
  - see what the running bot actually loaded.
- **Order ticket:** paper and live orders by hand, through the same risk
  checks.
- **Push updates:** server-sent events or a WebSocket instead of polling,
  fed from the bot's own feed instead of polling Upstox's quote API every
  2 s.
- **Trade journal:** notes and tags per trade, and the chart at entry and
  exit.
- **Strategy pages:** per-strategy equity curve, trade list and current
  parameters.
- **Login:** see [TODO](TODO.md) item 1.

## Paper trading

**Partial:** `scripts/paper_trade.py` (1,010 lines) is a second
implementation of the bot next to `main.py --mode paper` (1,029 lines). It
has its own fills, charges, squareoff and state file. It has none of the
intraday session rules, exchange-stop logic or control channel, and it
treats every trade as intraday.

**Extend with:** one bot. Make `main.py --mode paper` the only paper trader,
with a simulated broker that applies the same itemised charges, slippage and
partial fills. Keep `paper_trade.py` as a thin wrapper or delete it. Every
improvement then reaches paper and live at once.
