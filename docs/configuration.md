# Configuration Reference

Loony Trading uses two configuration files:
- `config/settings.yaml` — all trading parameters (safe to commit)
- `.env` — API keys and secrets (NEVER commit)

---

## .env File

Copy `.env.example` to `.env` and fill in your values.

```env
# ── Upstox ────────────────────────────────────────────────────────────────────
UPSTOX_API_KEY=          # from https://upstox.com/developer/
UPSTOX_API_SECRET=       # from Upstox developer console
UPSTOX_REDIRECT_URI=http://localhost:3561/callback   # must match exactly
UPSTOX_ACCESS_TOKEN=     # optional: paste pre-obtained token to skip OAuth on startup
UPSTOX_ANALYTICS_API_KEY=  # read-only analytics token (for market data only)

# ── Notifications ────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=      # from @BotFather
TELEGRAM_CHAT_ID=        # your chat or group ID

# ── Email ─────────────────────────────────────────────────────────────────────
SMTP_HOST=smtp.gmail.com
EMAIL_USER=you@gmail.com
EMAIL_PASSWORD=          # Gmail App Password (not your login password)
EMAIL_TO=alerts@example.com

# ── Crypto (secondary) ───────────────────────────────────────────────────────
BINANCE_API_KEY=
BINANCE_API_SECRET=

# ── News Sentiment ────────────────────────────────────────────────────────────
NEWS_API_KEY=            # from https://newsapi.org/
```

---

## settings.yaml Reference

### system

```yaml
system:
  name: loony-trading
  version: "1.1.0"
  mode: paper              # paper | live | backtest
  primary_market: upstox   # upstox | binance
  log_level: INFO          # DEBUG | INFO | WARNING | ERROR
  timezone: Asia/Kolkata
```

| Key | Options | Notes |
|---|---|---|
| `mode` | `paper` / `live` / `backtest` | Start with `paper`. Live requires authenticated Upstox session |
| `log_level` | `DEBUG` to `ERROR` | Set `DEBUG` to see every signal and feature value |
| `primary_market` | `upstox` / `binance` | Upstox for Indian equities, Binance for crypto |

---

### exchanges

```yaml
exchanges:
  upstox:
    api_key: "${UPSTOX_API_KEY}"       # reads from .env
    api_secret: "${UPSTOX_API_SECRET}"
    redirect_uri: "${UPSTOX_REDIRECT_URI}"
    access_token: "${UPSTOX_ACCESS_TOKEN}"
    token_file: "data/upstox_token.json"
    auth_port: 3561
    default_product: "CNC"           # CNC=delivery | MIS=intraday | NRML=F&O
```

**Upstox products:**
- `CNC` — Cash and Carry (delivery, held beyond same day)
- `MIS` — Margin Intraday Square-off (auto-squared at 15:15 IST)
- `NRML` — Normal (for F&O positions held overnight)

---

### assets

```yaml
assets:
  india_equity:
    - RELIANCE
    - TCS
    - HDFCBANK
    # ... add more NSE symbols here

  india_indices:
    - NIFTY50
    - NIFTYBANK

  india_fo:
    - NIFTY50        # near-month futures/options
    - BANKNIFTY

  crypto:
    - BTC/USDT
```

To add a new stock: add its NSE symbol to `india_equity`. The instrument registry
will resolve it to the correct `NSE_EQ|<ISIN>` key automatically.

---

### risk

```yaml
risk:
  max_risk_per_trade: 0.01          # 1% of portfolio per trade
  max_daily_drawdown: 0.05          # 5% daily loss → halt all new trades
  max_concurrent_trades: 10         # max open positions at once
  max_portfolio_risk: 0.20          # 20% total exposure
  stop_loss_atr_multiplier: 2.0     # SL = entry ± 2×ATR
  take_profit_atr_multiplier: 3.0   # TP = entry ± 3×ATR (R:R = 1.5)
  trailing_stop_pct: 0.02           # 2% trailing stop
  use_kelly_criterion: false        # true = fractional Kelly sizing
```

**Tuning tips:**
- Lower `max_risk_per_trade` to 0.005 (0.5%) for conservative sizing
- Set `use_kelly_criterion: true` only after you have 50+ trades of edge data
- `max_daily_drawdown: 0.03` if you want tighter daily limits

---

### strategies

```yaml
strategies:
  enabled:                 # current defaults, picked from a 2-year backtest
    - vwap_reversion
    - bollinger_reversion
    - donchian_breakout
    - zscore_reversion
    - rsi_momentum
    - candle_patterns
    - volume_momentum
    - vix_strategy
    - gift_nifty_gap
    - fii_dii
    - anchored_vwap
    - cumulative_delta
    - volume_profile
  weights:
    vwap_reversion: 1.5
    bollinger_reversion: 1.2
    # ... see config/settings.yaml
```

`scripts/tune_weights.py` recomputes `enabled` and `weights` from backtests.
`pair_trading` runs as a side-car and does not need to be listed.

To enable more strategies, add to the `enabled` list. Available names (must match
the strategy's `name` exactly — an unknown name is silently ignored):

| Name | Category |
|---|---|
| `ema_crossover` | Trend |
| `supertrend` | Trend |
| `donchian_breakout` | Trend |
| `mtf_trend` | Trend |
| `rsi_mean_reversion` | Mean reversion |
| `bollinger_reversion` | Mean reversion |
| `zscore_reversion` | Mean reversion |
| `vwap_reversion` | Mean reversion |
| `breakout_atr` | Breakout |
| `range_breakout` | Breakout |
| `sr_breakout` | Breakout |
| `macd_momentum` | Momentum |
| `rsi_momentum` | Momentum |
| `volume_momentum` | Momentum |
| `candle_patterns` | Price action |
| `order_book_imbalance` | Microstructure |
| `anchored_vwap` | Microstructure |
| `cumulative_delta` | Microstructure |
| `volume_profile` | Microstructure |
| `pair_trading` | Stat arb |
| `vix_strategy` | Volatility |
| `fii_dii` | Institutional |
| `gift_nifty_gap` | Gap |
| `ml_classifier` | ML (needs a trained model) |

Not available yet (not registered in `MetaStrategyEngine`, so listing them does nothing):
`pead`, `gamma_scalping`, `iron_condor`, `theta_decay`, `straddle_strangle`,
`expiry_day`. See [status.md](status.md#6-strategy-status).

---

### regime_detection

```yaml
regime_detection:
  adx_trend_threshold: 25       # ADX > 25 = trending
  adx_strong_threshold: 40      # ADX > 40 = strong trend
  volatility_high_pct: 0.03     # daily vol > 3% = volatile regime
  volatility_lookback: 20       # days to estimate vol
```

---

### ml

```yaml
ml:
  train_lookback_days: 180       # history used for training
  retrain_interval_hours: 24     # retrain every 24h

  xgboost:
    n_estimators: 300
    max_depth: 6
    learning_rate: 0.05

  lightgbm:
    num_leaves: 63
    n_estimators: 300
    learning_rate: 0.05

  lstm:
    sequence_length: 60
    hidden_units: 128
    dropout: 0.2
    epochs: 50
    batch_size: 32

  reinforcement:
    enabled: false
    algorithm: PPO
    total_timesteps: 100000
```

---

### portfolio

```yaml
portfolio:
  initial_capital: 500000      # ₹5,00,000 starting capital
  base_currency: INR
  rebalance_interval_hours: 24
  correlation_limit: 0.7       # block new trade if corr > 0.7 with existing
```

---

### india_market

```yaml
india_market:
  open_time: "09:15"           # IST — NSE equity session open
  close_time: "15:30"          # IST — NSE equity session close
  pre_open: "09:00"            # pre-open order matching
  auto_squareoff_time: "15:15" # MIS auto-squareoff
  holidays: [...]              # fallback list; live list is fetched from NSE
```

The holiday calendar is fetched from NSE and cached in `data/nse_holidays.json`.
The `holidays` list is the fallback when NSE is unreachable (2026 is already filled in):
```yaml
  holidays:
    - "2026-01-26"   # Republic Day
    - "2026-08-15"   # Independence Day
    - "2026-10-02"   # Gandhi Jayanti
```

---

### notifications

```yaml
notifications:
  telegram:
    enabled: false        # set true after adding TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
  email:
    enabled: false
    smtp_host: "${SMTP_HOST}"
    smtp_port: 587
    user: "${EMAIL_USER}"
    password: "${EMAIL_PASSWORD}"
    to: "${EMAIL_TO}"
```

---

### dashboard

```yaml
dashboard:
  host: "0.0.0.0"
  port: 8501                 # stale — the dashboard actually serves on 8000 (API) / 5163 (Vite dev)
  refresh_interval_sec: 5    # how often the dashboard polls for new data
```

---

## Common Config Scenarios

### Conservative starter setup
```yaml
system:
  mode: paper
risk:
  max_risk_per_trade: 0.005    # 0.5% per trade
  max_daily_drawdown: 0.03     # 3% daily limit
  max_concurrent_trades: 5
strategies:
  enabled:
    - ema_crossover
    - rsi_mean_reversion
    - macd_momentum
```

### Aggressive intraday setup
```yaml
system:
  mode: live
exchanges:
  upstox:
    default_product: "MIS"     # intraday, auto-squared at 15:15
risk:
  max_risk_per_trade: 0.015
  trailing_stop_pct: 0.015
strategies:
  enabled:
    - range_breakout
    - vwap_reversion
    - order_book_imbalance
    - cumulative_delta
    - anchored_vwap
```

### Options income setup
```yaml
strategies:
  enabled:
    - vix_strategy
    # iron_condor, theta_decay and expiry_day are not wired into the engine yet
```
