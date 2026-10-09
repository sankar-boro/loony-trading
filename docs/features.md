# Features Reference

Complete list of every module implemented in Loony Trading.

---

## Data Engine

### Upstox Market Data (`data_engine/upstox/`)

| Module | What it does |
|---|---|
| `auth.py` | OAuth 2.0 token lifecycle — opens browser, captures redirect, refreshes automatically |
| `instruments.py` | Instrument master: `NSE_EQ|<ISIN>`, `NSE_INDEX|Nifty 50`, F&O lookup |
| `market_hours.py` | NSE open/close detection, holiday calendar, IST timezone utilities |
| `upstox_data.py` | Historical OHLCV (daily, weekly, monthly, intraday 1m/5m/15m/30m/1h) |
| `upstox_feed.py` | WebSocket real-time price feed (LTP, full OHLC, depth, OI) |
| `india_vix.py` | India VIX level monitor, percentile ranking, regime classification |
| `iv_surface.py` | IV surface from options chain — ATM IV, skew, term structure, smile |

**Live instrument key format:**
```python
NIFTY50    = "NSE_INDEX|Nifty 50"
BANKNIFTY  = "NSE_INDEX|Nifty Bank"
RELIANCE   = "NSE_EQ|INE002A01018"   # use ISIN, not symbol name
```

**Fetching historical data:**
```python
from data_engine.upstox.upstox_data import UpstoxDataEngine
engine = UpstoxDataEngine(access_token=os.getenv("UPSTOX_ACCESS_TOKEN"))
df = engine.get_historical_data("NSE_INDEX|Nifty 50", interval="day", days=90)
```

---

### NSE Public Data (`data_engine/nse_data.py`)

Scrapes NSE public APIs (no authentication needed):
- FII/DII daily buy/sell flows
- F&O ban list (stocks in ban period today)
- Corporate actions calendar

---

### Order Book (`data_engine/orderbook.py`)

Real-time L2 order book analysis:
- Bid/ask imbalance ratio
- Whale pressure detection (large orders in top 5 levels)
- Spread monitoring

---

### GIFT Nifty Pre-Market (`data_engine/gift_nifty.py`)

- Fetches GIFT Nifty (SGX Nifty successor) price before Indian market opens
- Computes gap % vs previous NSE close
- Classifies: `strong_gap_up`, `weak_gap_up`, `flat`, `weak_gap_down`, `strong_gap_down`

---

### Circuit Breaker Detector (`data_engine/circuit_detector.py`)

SEBI circuit breaker rules:
- **Market-wide:** 10% → 45 min halt (before 1pm) / 15 min (1-2:30pm) / no halt (after 2:30pm)
- **Market-wide:** 15% → 105 min (before 1pm) / 45 min (1-2pm) / rest-of-day (after 2pm)
- **Market-wide:** 20% → rest-of-day halt
- **Stock-level:** ±10% default (configurable per symbol)

```python
from data_engine.circuit_detector import CircuitBreakerDetector
det = CircuitBreakerDetector()
status = det.check_stock(symbol="RELIANCE", current_price=2950, prev_close=2800)
# status.is_circuit_hit, status.circuit_type, status.pct_change
```

---

## Feature Engine

### Technical Indicators (`feature_engine/indicators.py`)

40+ pure-Python indicators (no ta-lib dependency):

| Indicator | Function |
|---|---|
| SMA / EMA | Simple and exponential moving averages |
| RSI | Relative Strength Index (Wilder smoothing) |
| MACD | MACD line, signal, histogram |
| Bollinger Bands | Upper/lower bands, %B, bandwidth |
| ATR | Average True Range |
| ADX | Average Directional Index (trend strength) |
| Stochastic | %K and %D |
| VWAP | Session-anchored Volume-Weighted Average Price |
| OBV | On-Balance Volume |
| Supertrend | ATR-based trend direction line |
| Donchian Channel | N-period high/low channel |
| Keltner Channel | EMA ± 1.5×ATR |
| Williams %R | Overbought/oversold oscillator |
| CCI | Commodity Channel Index |
| MFI | Money Flow Index |
| DEMA / TEMA | Double/Triple Exponential MA |

---

### Feature Builder (`feature_engine/feature_builder.py`)

```python
from feature_engine.feature_builder import FeatureBuilder
fb = FeatureBuilder()
df_features = fb.build(df)   # input: OHLCV DataFrame, output: 40+ feature columns
```

Features added: all indicators above + returns (1d, 5d, 20d), volatility ratios,
volume z-score, price position within Bollinger bands, trend strength composite.

---

### Advanced Features (`feature_engine/advanced_features.py`)

Microstructure and regime-specific features:
- Realized volatility (5-min, hourly, daily)
- Volume-weighted realized vol
- Order flow imbalance proxy
- Amihud illiquidity ratio
- Market impact estimate
- Intraday pattern features (opening range, morning reversal probability)

```python
from feature_engine.advanced_features import AdvancedFeatureBuilder
afb = AdvancedFeatureBuilder()
df_advanced = afb.build(df)   # needs 250+ rows for EMA_200
```

---

### Options Greeks (`feature_engine/greeks.py`)

Black-Scholes Greeks for any option:

```python
from feature_engine.greeks import Greeks
g = Greeks(S=24000, K=24000, T=30, r=0.065, sigma=0.15, opt="call")
# g.delta, g.gamma, g.theta, g.vega, g.rho
```

Implied volatility solver (Newton-Raphson):
```python
from feature_engine.greeks import implied_volatility
iv = implied_volatility(market_price=250, S=24000, K=24000, T=30, r=0.065, opt="call")
```

---

## Strategies

See [strategies.md](strategies.md) for full detail on each strategy.

**Quick count:** 25+ strategies across 14 categories. 23 are registered in the
engine (plus pair trading as a side-car); options strategies and PEAD are not wired yet — see [status.md](status.md#6-strategy-status).

---

## ML Models

### XGBoost (`ml_models/xgb_model.py`)

3-class classifier (0=sell, 1=hold, 2=buy):
```python
from ml_models.xgb_model import XGBoostModel
model = XGBoostModel()
model.train(X_train, y_train)
proba = model.predict_proba(X_test)  # shape (n, 3)
```

---

### LightGBM (`ml_models/lgbm_model.py`)

Same interface as XGBoost, typically faster to train:
```python
from ml_models.lgbm_model import LightGBMModel
```

---

### LSTM (`ml_models/lstm_model.py`)

Sequence model for temporal patterns:
```python
from ml_models.lstm_model import LSTMModel
model = LSTMModel(sequence_length=60, hidden_units=128)
```

---

### Temporal Fusion Transformer (`ml_models/tft_model.py`)

Pure numpy/sklearn TFT — no PyTorch required:
```python
from ml_models.tft_model import TemporalFusionTransformer
tft = TemporalFusionTransformer(input_size=40, hidden_size=64, num_heads=4)
tft.fit(X, y)           # y: 0/1/2 class labels
proba = tft.predict_proba(X_test)   # shape (n, 3)
horizons = tft.predict_multi_horizon(X_recent)  # {1: cls, 5: cls, 10: cls}
```

---

### Ensemble (`ml_models/ensemble.py`)

Weighted soft-voting ensemble over any combination of models:
```python
from ml_models.ensemble import EnsembleModel
ens = EnsembleModel(models=[xgb, lgbm, lstm], weights=[1.2, 1.0, 0.8])
signal = ens.predict(features)
```

---

### Online Learning + Drift Detection (`ml_models/online_model.py`)

Adaptive model that updates on every trade outcome:

```python
from ml_models.online_model import AdaptiveModel, PageHinkleyDetector

# Drift detector — alerts when performance drops
ph = PageHinkleyDetector(threshold=10.0, alpha=0.01)
if ph.update(new_sharpe_value):
    print("Concept drift detected — retrain needed")

# Adaptive model — wraps a batch model + online ensemble
model = AdaptiveModel(batch_model=xgb_model)
proba = model.predict_proba(x_array, x_dict)
model.update(x_array, true_label)   # incorporate new label after trade closes
```

---

### Bayesian Hyperparameter Optimisation (`ml_models/bayesian_opt.py`)

Finds optimal strategy parameters without exhaustive grid search:

```python
from ml_models.bayesian_opt import BayesianOptimizer

opt = BayesianOptimizer(
    param_space={
        "entry_z":  (1.5, 4.0),          # continuous
        "exit_z":   (0.1, 1.5),
        "lookback": (20, 120, "int"),     # integer
    },
    objective_fn=lambda p: backtest_sharpe(**p),
    n_trials=50,
)
result = opt.optimize()
print(result.summary())   # best params + Sharpe
```

Uses Optuna TPE (preferred) or Gaussian Process + Expected Improvement (fallback).

Convenience wrappers:
```python
from ml_models.bayesian_opt import optimize_pair_trading, optimize_vix_strategy
result = optimize_pair_trading(my_backtest_fn, n_trials=50)
```

---

### Reinforcement Learning (`ml_models/rl_agent.py`)

PPO/DQN agent trained on historical price sequences:
```python
from ml_models.rl_agent import RLTradingAgent
agent = RLTradingAgent(state_size=40, action_size=3)
agent.train(df_train, episodes=100)
action = agent.act(current_state)   # 0=sell, 1=hold, 2=buy
```

---

## Execution Engine

### TWAP/VWAP Smart Orders (`execution_engine/smart_order.py`)

Splits large orders over time to minimise market impact:

```python
from execution_engine.smart_order import TWAPOrder, VWAPOrder

# TWAP: equal slices over N intervals
twap = TWAPOrder(symbol="RELIANCE", total_qty=1000, intervals=10, interval_sec=60)
slices = twap.get_next_slice()   # returns qty for this interval

# VWAP: slices weighted by NSE historical volume profile (U-shape)
vwap = VWAPOrder(symbol="RELIANCE", total_qty=1000, start_time="09:30", end_time="15:00")
```

Transaction cost analysis:
```python
from execution_engine.smart_order import TransactionCostAnalyzer
tca = TransactionCostAnalyzer()
cost = tca.estimate(symbol, qty, price, side="BUY")
# cost.brokerage, cost.stt, cost.stamp_duty, cost.total_bps
```

---

### Upstox Order Placement (`execution_engine/upstox_executor.py`)

```python
from execution_engine.upstox_executor import UpstoxExecutor
exec = UpstoxExecutor(access_token=token)
order_id = exec.place_order(
    symbol="NSE_EQ|INE002A01018",
    qty=10,
    side="BUY",
    order_type="MARKET",
    product="CNC",   # CNC=delivery, MIS=intraday, NRML=F&O
)
```

GTT (Good Till Triggered) orders for bracket order simulation:
```python
exec.place_gtt(symbol, qty, trigger_price, limit_price)
```

---

## Risk Manager

### Position Sizing & Stop-Loss (`risk_manager/risk_manager.py`)

```python
from risk_manager.risk_manager import RiskManager
rm = RiskManager(capital=500000, config=settings["risk"])
qty = rm.position_size(symbol, entry_price, stop_price)
rm.validate_trade(signal)   # raises if limits exceeded
rm.update_trailing_stop(symbol, current_price)
```

Rules enforced:
- Max 1% capital per trade (configurable)
- Max 5% daily drawdown → halt new trades
- Max 20% total portfolio exposure
- Correlation guard: blocks new trade if >0.7 correlated with existing position
- Trailing stops: ATR-adjusted, ratchets up on profit

---

### CVaR Risk Manager (`risk_manager/cvar.py`)

Conditional Value-at-Risk (Expected Shortfall):

```python
from risk_manager.cvar import CVaRRiskManager
cvar_rm = CVaRRiskManager(capital=500000, confidence=0.95)
cvar_rm.add_return(daily_pnl_pct)
result = cvar_rm.compute()
# result.var_95, result.cvar_95, result.max_position_size
```

Three methods: historical simulation, parametric (normal), Cornish-Fisher (skew/kurtosis adjusted).

---

## Portfolio Manager

### Multi-Asset Allocation (`portfolio_manager/portfolio.py`)

Tracks all open positions, enforces correlation limits, computes portfolio-level metrics.

---

### Beta-Neutral Hedging (`portfolio_manager/beta_neutral.py`)

Hedges portfolio beta to Nifty50 using Nifty futures:

```python
from portfolio_manager.beta_neutral import BetaNeutralPortfolio
bnp = BetaNeutralPortfolio(capital=500000)
bnp.add_position("RELIANCE", qty=100, beta=1.2)
hedge = bnp.compute_hedge()
# hedge.nifty_futures_qty, hedge.direction
```

Rolling beta estimation via OLS regression on 63-day returns.

---

## Analytics

### Live P&L Tracker (`analytics/live_pnl.py`)

Real-time trade tracking with automatic strategy management:

```python
from analytics.live_pnl import LivePnLTracker
tracker = LivePnLTracker(capital=500000)
tracker.record_trade(
    trade_id="T001", strategy="ema_crossover", symbol="RELIANCE",
    direction="BUY", qty=10, entry_price=2800.0, exit_price=2860.0
)
```

Auto-disable rules:
- Strategy loses >2% of capital in one day → disabled for the day
- Portfolio drawdown >5% → all strategies halted
- 5 consecutive losing trades → size reduced to 50%

Daily reset at market open:
```python
tracker.reset_daily()
summary = tracker.portfolio_summary()
```

---

### Factor Model (`analytics/factor_model.py`)

India Fama-French factor decomposition:
- Factors: Nifty50 (market), BankNifty, NiftyIT, NiftyFMCG, NiftyAuto, NiftyMidcap
- Decomposes P&L into: market beta return, factor tilts, alpha (skill)

```python
from analytics.factor_model import FactorModel
fm = FactorModel()
fm.fit(returns_df, factor_returns_df)
report = fm.decompose(portfolio_returns)
# report.alpha, report.factor_exposures, report.r_squared
```

---

### Monte Carlo Backtesting (`backtester/monte_carlo.py`)

Confidence intervals for strategy performance:

```python
from backtester.monte_carlo import run_monte_carlo
result = run_monte_carlo(
    trade_returns=[0.02, -0.01, 0.015, ...],   # list of trade P&L%
    n_simulations=1000,
    method="bootstrap",   # bootstrap | block_bootstrap | parametric
)
print(result.summary())
# Return:  8.2% ± 3.1% [5th: 3.1%, 95th: 14.2%]
# Max DD:  6.4% (95th: 11.2%)
# Sharpe:  1.82 [5th: 0.91, 95th: 2.74]
# p-value: 0.003   (strong evidence strategy has edge)
```

---

### Stress Testing (`backtester/stress_test.py`)

Simulates 5 Indian market crises:
- COVID crash (Feb-Mar 2020): −38% Nifty
- IL&FS crisis (Sept-Oct 2018): −15%
- Demonetisation (Nov-Dec 2016): −12%
- China meltdown (Aug 2015): −18%
- Taper tantrum (May-Jun 2013): −14%

```python
from backtester.stress_test import StressTester
st = StressTester()
results = st.run_all(portfolio_returns)
for r in results:
    print(r.scenario, r.portfolio_return, r.survived)
```

---

## Alerting

### Telegram Alerts (`utils/telegram_alerts.py`)

Non-blocking alerts (background threads, never delays trading loop):

```python
from utils.telegram_alerts import TelegramAlerter
alerter = TelegramAlerter()   # reads TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID from env

alerter.trade_alert("ema_crossover", "RELIANCE", "BUY", 10, 2840.0, pnl=None)
alerter.daily_summary(capital=500000, daily_pnl=4200, trade_count=8, win_rate=0.625, drawdown_pct=0.8)
alerter.risk_alert("drawdown", "Portfolio DD hit 4.2%", level="WARNING")
alerter.circuit_alert("YESBANK", "lower", 18.50)
alerter.strategy_disabled_alert("pair_trading", "daily_loss_exceeded")
```

Setup:
1. Create bot via `@BotFather` in Telegram → get `TELEGRAM_BOT_TOKEN`
2. Send any message to your bot → `https://api.telegram.org/bot<TOKEN>/getUpdates` → get `TELEGRAM_CHAT_ID`
3. Add both to `.env`

---

## Dashboard

FastAPI + React app at `localhost:5163` (API on `localhost:8000`):

```bash
bash dashboard/start.sh          # dev mode
bash dashboard/start.sh --prod   # production build
```

| Page | Content |
|---|---|
| Dashboard | Real-time prices, current positions, latest signals |
| Chart | TradingView-style candlestick chart per symbol |
| Positions | Open positions |
| Trades | Trade log |
| Strategies | Per-strategy trade count, win rate and P&L |
| Backtest | Performance metrics, Monte Carlo results |
| Daily PnL | Equity curve, drawdown chart |
| News | Classified news events per stock |
| Signals | Composite signal scores, "why is it moving" |
| Copilot | AI Q&A over signals and news |
| Watchlists | Named stock lists |
| Alerts | Rule-based alerts and trigger history |
| Portfolio Risk | Exposure, concentration, correlation |
| Intraday Lab | Intraday scans and alert evaluation |
| Docs | These markdown docs, rendered in the browser |

---

## Structured Logging

All logs are structured JSON written to `logs/`:

```bash
# Watch trading activity
tail -f logs/trading.log | python -m json.tool

# Watch trade entries/exits only
tail -f logs/trades.jsonl

# Filter by strategy
grep "ema_crossover" logs/trading.log

# Filter errors
grep '"level":"ERROR"' logs/trading.log | python -m json.tool

# Filter critical risk events
grep '"level":"CRITICAL"' logs/trading.log
```

Example log entry:
```json
{
  "timestamp": "2026-05-27T10:15:32.441",
  "level": "INFO",
  "logger": "live_pnl",
  "message": "Trade: ema_crossover/RELIANCE BUY 10 P&L=₹+600 (0.12%) capital=₹500,600"
}
```
