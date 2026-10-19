# Configuration Reference

All trading parameters live in `config/settings.yaml`; secrets live in `.env`
([Environment Variables](environment.md)). This chapter documents every key in
`settings.yaml`, section by section.

## How settings are loaded

`config/loader.py` reads the YAML once per process into `settings`
(`from config import settings`):

- Values written as `"${NAME}"` are replaced with the environment variable
  `NAME` (empty if unset), so secrets never need to be typed into the file.
- `settings.get("risk.max_risk_per_trade", default)` reads dotted paths;
  `settings.as_dict()` returns the whole tree, which is what components receive
  as `cfg`.
- Bots and scripts read the file when they start — **restart them after
  editing**. Dashboard endpoints mostly re-read it per request.

Keys marked *informational* are not read by any code today; changing them has
no effect.

## system

| Key | Default | Meaning |
|---|---|---|
| `name` | `loony-trading` | Informational |
| `version` | `"1.1.0"` | Informational |
| `mode` | `paper` | Default `--mode` for `main.py`: `paper`, `live` or `backtest` |
| `primary_market` | `upstox` | Informational |
| `log_level` | `INFO` | Log level of the `main` logger (`DEBUG`…`ERROR`) |
| `timezone` | `Asia/Kolkata` | Scheduler timezone |

## exchanges

### exchanges.upstox

| Key | Default | Meaning |
|---|---|---|
| `api_key`, `api_secret`, `redirect_uri` | from `.env` | OAuth app credentials |
| `access_token` | `${UPSTOX_ACCESS_TOKEN}` | Token used when no valid token file exists |
| `token_file` | `data/upstox_token.json` | Where the daily token is saved |
| `auth_port` | `3561` | Local port for the OAuth redirect (`main.py --mode auth`) |
| `default_product` | `CNC` | Product for every order: `CNC` (delivery), `MIS` (intraday — squared off at 15:14), `NRML` (F&O carry) |

### exchanges.binance, exchanges.alpaca

Credentials for the dormant crypto add-on (`api_key`, `api_secret`, `sandbox`)
and a placeholder Alpaca section. `rate_limit` and `base_url` are
informational.

## assets

| Key | Meaning |
|---|---|
| `india_equity` | Stocks the live bot trades (default 15 large caps) |
| `india_indices` | Indices the bot watches (`NIFTY50`, `NIFTYBANK`) — macro strategies signal on these |
| `india_fo` | Informational (F&O trading is not wired) |
| `crypto` | Pairs for the crypto add-on / `--market crypto` backtests |

Symbols must exist in `config/instruments.py`. The dashboard and MarketPulse
use the whole 91-stock universe regardless of this list.

## timeframes

| Key | Default | Meaning |
|---|---|---|
| `primary` | `1d` | Bars the bot loads for every symbol; `--mode backtest` uses it |
| `intraday` | `30m` | Live bars the bot scores equities on. Not `15m`: Upstox returns HTTP 400 for 5/15-minute candles on some accounts |
| `secondary` | `[15m, 1h, 1d]` | Informational |

Timeframe strings: `1m`, `3m`, `5m`, `10m`, `15m`, `30m`, `1h`, `60m`, `2h`,
`4h`, `1d`, `1w`, `1M`.

## risk

| Key | Default | Meaning |
|---|---|---|
| `max_risk_per_trade` | `0.01` | Fraction of capital risked per trade (sizing) |
| `max_daily_drawdown` | `0.05` | Stop opening trades after this daily loss; also the intraday kill-switch level (realised + unrealised) |
| `max_concurrent_trades` | `10` | Open positions limit |
| `max_portfolio_risk` | `0.20` | Largest single position as a fraction of capital (the Portfolio Risk page also uses it as a total-exposure warning) |
| `stop_loss_atr_multiplier`, `take_profit_atr_multiplier` | `2.0`, `3.0` | Informational — stops come from each strategy |
| `trailing_stop_pct` | `0.02` | Trailing stop distance (live, and in backtests from each bar's high/low) |
| `max_sector_exposure` | `0.30` | Largest share of capital (at entry prices) in one sector; new entries are trimmed to fit and rejected when the sector is full. `0` = no cap ([Sector exposure cap](../engine/risk-management.md#sector-exposure-cap)) |
| `use_kelly_criterion` | `false` | Size with fractional Kelly instead |
| `kelly_fraction` | `0.25` | Fraction of full Kelly |

Details: [Risk Management](../engine/risk-management.md).

## intraday

Session rules, operator controls and monitoring for the live bot
(`main.py`). Details: [Intraday Session Controls](../engine/intraday-controls.md).

| Key | Default | Meaning |
|---|---|---|
| `entry_start` | `"09:30"` | No new MIS entries before this time (IST, `"HH:MM"`) |
| `entry_end` | `"14:45"` | No new MIS entries after this time |
| `max_trades_per_day` | `20` | Filled entries per day across all symbols (`0` = no cap) |
| `max_trades_per_symbol` | `3` | Filled entries per symbol per day (`0` = no cap) |
| `cooldown_minutes_after_stop` | `30` | No re-entry into a symbol this long after a stop-loss exit |
| `profit_lock_pct` | `0.0` | Halt new entries once day P&L reaches this fraction of capital (`0` = off) |
| `strategy_limits.max_daily_loss_pct` | `0.01` | Switch a strategy off for the day once its realised loss reaches this fraction of capital (`0` = off) |
| `strategy_limits.max_consecutive_losses` | `4` | ... or after this many losing trades in a row (`0` = off) |
| `kill_switch.flatten_on_daily_loss` | `true` | When day P&L (realised + unrealised) reaches −`risk.max_daily_drawdown` × capital, close every position as well as halting entries |
| `heartbeat_minutes` | `5` | Alert once if no tick arrives for this long during market hours |
| `record_bars` | `true` | Save every finished 1-minute bar to `data/live_bars/` |
| `exchange_stops` | `false` | Live only: protect each position with an SL-M order at the broker, trailed with the stop |

## execution

| Key | Default | Meaning |
|---|---|---|
| `order_type` | `limit` | `market`, `limit` or `smart` (market above 0.85 confidence, else limit) |
| `slippage_pct` | `0.0005` | Paper-fill and backtest slippage per fill |
| `commission_intraday` | `0.00055` | Backtest round-trip cost, MIS |
| `commission_delivery` | `0.0021` | Backtest round-trip cost, CNC |
| `commission_futures` | `0.0006` | Pair backtest round-trip cost per leg (futures) |
| `retry_attempts` | `3` | Crypto executor only — Upstox orders are never retried |
| `retry_delay_ms` | `500` | Crypto executor retry delay |
| `latency_budget_ms` | `100` | Informational |
| `reconcile_interval_sec` | `300` | Live: broker reconciliation interval |
| `max_tick_jump_pct` | `0.20` | Drop ticks moving more than this from the last price |
| `chase_attempts` | `2` | Live: times an unfilled limit order is re-priced toward the market before the rest is cancelled (`0` = off) |
| `chase_wait_sec` | `10` | Seconds to wait for a fill after each re-price |
| `max_chase_pct` | `0.003` | Never chase more than this from the original limit |
| `upstox_product` | *(unset)* | Overrides `exchanges.upstox.default_product` |

## data

| Key | Default | Meaning |
|---|---|---|
| `lookback_days` | `365` | History the bot loads per symbol |
| `cache_dir` | `./data/cache` | Candle cache directory |
| `warmup_bars` | `200` | Bars skipped before a backtest starts trading (indicator warm-up) |

## strategies

```yaml
strategies:
  enabled: [vwap_reversion, bollinger_reversion, donchian_breakout, …]
  weights: {vwap_reversion: 1.5, bollinger_reversion: 1.2, …}
```

| Key | Meaning |
|---|---|
| `enabled` | Strategy names to run; empty = all. Unknown names are ignored silently — check against `GET /api/config` → `all_strategies` |
| `weights` | Multiplier on each strategy's confidence when ranking signals; default 1.0 |

Valid names: `ema_crossover`, `mtf_trend`, `supertrend`, `donchian_breakout`,
`rsi_mean_reversion`, `bollinger_reversion`, `zscore_reversion`,
`vwap_reversion`, `sr_breakout`, `breakout_atr`, `range_breakout`,
`macd_momentum`, `rsi_momentum`, `volume_momentum`, `order_book_imbalance`,
`anchored_vwap`, `cumulative_delta`, `volume_profile`, `candle_patterns`,
`vix_strategy`, `gift_nifty_gap`, `fii_dii`, `ml_classifier`. (`pair_trading`
is a side-car; options strategies and `pead` are not wired.)

`scripts/tune_weights.py` rewrites both keys from backtests;
`scripts/train_ml.py --enable` appends `ml_classifier`.

### Pairs

`strategies.pairs` lists pairs the live bot trades as one unit, for example
`pairs: [[TCS, INFY]]`. It is empty by default. Pairs need MIS (a short leg).
Find candidates with `scripts/find_pairs.py`. See
[Pair Trading](../engine/strategies-stat-arb.md#live-trading).

### Strategy parameters

`strategies.params.<strategy>.<key>` overrides a strategy's parameter, for
example `strategies.params.donchian_breakout.dc_period: 55`. Every strategy
has `max_hold_bars` (time stop, `0` = off), `atr_stop_mult` and
`atr_target_mult`; the rest are listed in each strategy chapter and on the
Strategies page. Legacy top-level keys (`ema_fast: 12`) are still read when
no nested value is set. The microstructure, volatility, gap, institutional
and options strategies read their own sections (`microstructure:`,
`volatility:`, `gap:`, `institutional:`, `options:`). See
[The Strategy Framework](../engine/strategy-framework.md#where-parameters-come-from).

## signal_engine

| Key | Default | Meaning |
|---|---|---|
| `weights.catalyst` … `weights.risk` | 0.25, 0.20, 0.15, 0.15, 0.10, 0.10, 0.05 | Composite-score weights; keep the sum at 1 |
| `quality_gate.min_score` | `70` | Score needed for bullish/bearish |
| `quality_gate.min_confidence` | `65` | Strategy confidence (×100) needed for bullish/bearish |
| `quality_gate.watch_score` | `50` | Score needed for watch |

Details: [Composite Signals](../marketpulse/composite-signals.md).

## regime_detection

| Key | Default | Meaning |
|---|---|---|
| `adx_trend_threshold` | `25` | ADX at or above → trending |
| `adx_strong_threshold` | `40` | Read but not used in classification |
| `volatility_high_pct` | `0.03` | 20-bar return volatility above → high volatility (below 40 % of it → low volatility) |
| `volatility_lookback` | `20` | Bars for the volatility estimate |
| `use_hmm` | `true` | Use fitted, gated HMM models where they exist ([The HMM detector](../engine/strategy-framework.md#the-hmm-detector)) |
| `hmm_max_age_days` | `45` | Ignore HMM models older than this |
| `breakout_lookback`, `breakout_range_mult` | `20`, `1.5` | Breakout: close beyond the prior N bars' range on a bar this many times the average range |
| `crisis_vol_mult`, `crisis_drop_pct` | `2.0`, `0.08` | Crisis: volatility this many times `volatility_high_pct` and this fall over five bars |

## ml

| Key | Default | Meaning |
|---|---|---|
| `train_lookback_days` | `180` | `main.py --mode train` uses at least 365 |
| `retrain_interval_hours` | `24` | Informational — retraining is the weekly scheduler job |
| `xgboost.*`, `lightgbm.*` | | Hyperparameters for `ModelTrainer` (the gated `train_ml.py` uses its own fixed values) |
| `lstm.*` | 60, 128, 0.2, 50, 32 | `LSTMModel`: sequence length, units, dropout, epochs, batch size |
| `reinforcement.enabled`, `total_timesteps` | `false`, 100000 | RL agent (skeleton); `algorithm` informational |

## portfolio

| Key | Default | Meaning |
|---|---|---|
| `initial_capital` | `500000` | Starting capital (₹) for the bot, backtests and dashboard maths |
| `base_currency` | `INR` | Currency label |
| `rebalance_interval_hours` | `24` | Informational |
| `correlation_limit` | `0.7` | Live bot skips entries correlated above this with an open position |

## scheduler

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Start background jobs with the dashboard backend |
| `news_interval_seconds` | `60` | News ingestion |
| `signal_interval_seconds` | `300` | Composite scoring (daily bars) |
| `alert_interval_seconds` | `300` | Alert evaluation |
| `market_hours_only` | `true` | Skip signal/alert jobs while NSE is closed |
| `historical_backfill_hour`, `_minute`, `_min_age_days` | 18, 0, 7 | Daily analogue backfill |
| `signal_outcomes_enabled`, `_hour`, `_minute` | true, 16, 30 | Weekday signal outcome recording |
| `ml_retrain_enabled`, `_day_of_week`, `_hour`, `_days` | true, sun, 6, 730 | Weekly gated ML retrain |
| `regime_refit_enabled`, `_day_of_week`, `_hour`, `_days` | false, sun, 7, 1095 | Weekly gated HMM regime refit (opt-in: new models change how the bot classifies regimes) |
| `intraday_enabled` | `false` | Opt-in intraday scoring and alerts |
| `intraday_timeframe` | `30m` | Bar size for the intraday track |
| `intraday_signal_interval_seconds`, `intraday_alert_interval_seconds` | 900, 900 | Intraday cadence |
| `intraday_lookback_days` | `5` | History per intraday scan |

Details: [The Scheduler](../marketpulse/scheduler.md).

## india_market

| Key | Meaning |
|---|---|
| `holidays` | NSE trading holidays (`"YYYY-MM-DD"`); used as the **offline fallback** when NSE's holiday API and cache are unavailable. Keep it current each year |
| `open_time`, `close_time`, `pre_open`, `amo_window_start`, `amo_window_end` | Informational — session times are fixed in `market_hours.py` (09:15–15:30) |
| `auto_squareoff_time` | Informational (`15:15`) — the code squares off at **15:14** |

## notifications

| Key | Default | Meaning |
|---|---|---|
| `telegram.enabled` | `true` | Live/paper bot (`main.py`) sends Telegram messages |
| `telegram.bot_token`, `telegram.chat_id` | from `.env` | |
| `email.enabled` | `false` | Bot also e-mails notifications |
| `email.smtp_host`, `smtp_port`, `user`, `password`, `to` | from `.env`, 587 | SMTP with STARTTLS |
| `telegram.min_level`, `email.min_level` | `INFO`, `WARNING` | Lowest level each channel carries |
| `dedupe_minutes` | `10` | The same message at most once in this window |
| `rate_limit_per_minute` | `20` | Messages a minute (CRITICAL is exempt) |
| `alert_cooldown_minutes` | `240` | An alert does not re-trigger for the same stock within this |

Other components use the `TELEGRAM_*` environment variables directly
([Notifications](../operations/notifications.md)).

## dashboard

`host`, `port` (8000) and `refresh_interval_sec` are informational: the
backend's address is set on the `uvicorn` command line (`dashboard/start.sh`,
Docker Compose) and each page sets its own refresh interval.

## Example profiles

**Conservative paper trading**

```yaml
system: {mode: paper}
risk: {max_risk_per_trade: 0.005, max_daily_drawdown: 0.03, max_concurrent_trades: 5}
strategies:
  enabled: [donchian_breakout, bollinger_reversion, zscore_reversion]
```

**Intraday (MIS)**

```yaml
exchanges:
  upstox: {default_product: MIS}
timeframes: {intraday: 30m}
risk: {max_risk_per_trade: 0.005, max_daily_drawdown: 0.02, trailing_stop_pct: 0.015}
intraday:
  entry_start: "09:30"
  entry_end: "14:30"
  max_trades_per_day: 10
  max_trades_per_symbol: 2
  profit_lock_pct: 0.015
  exchange_stops: true       # live only
strategies:
  enabled: [vwap_reversion, anchored_vwap, cumulative_delta, range_breakout, volume_profile]
```

**Research server (MarketPulse only)**

```yaml
scheduler:
  enabled: true
  news_interval_seconds: 900
  signal_interval_seconds: 900
  intraday_enabled: true
```
