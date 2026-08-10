# Loony Trading

Algorithmic trading system for Indian equity markets (Upstox) with 25+ strategies,
ML signal stacking, live risk management, and Telegram alerts.

**Version:** 1.1.0 | **Primary market:** NSE/BSE via Upstox | **Mode:** Paper / Live / Backtest

---

## Quick Links

| Document | What's inside |
|---|---|
| [docs/quickstart.md](docs/quickstart.md) | Install, configure, and run in 10 minutes |
| [docs/features.md](docs/features.md) | Every module implemented and what it does |
| [docs/strategies.md](docs/strategies.md) | All 25+ strategies — logic, params, signals |
| [docs/configuration.md](docs/configuration.md) | Full config reference (settings.yaml + .env) |
| [docs/testing.md](docs/testing.md) | Running tests, live API tests, reading logs |
| [docs/known_issues.md](docs/known_issues.md) | Known bugs, missing pieces, improvement roadmap |

---

## 30-Second Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # fill UPSTOX_API_KEY, UPSTOX_API_SECRET
python main.py --mode paper   # paper trading — no real money
```

Dashboard: `bash dashboard/start.sh` → open http://localhost:5173

---

## What It Does

```
Upstox live feed
      │
      ▼
 data_engine/        ← historical OHLCV, order book, VIX, FII/DII, options chain
      │
      ▼
 feature_engine/     ← 40+ indicators (RSI, MACD, ATR, Greeks, microstructure)
      │
      ▼
 strategies/         ← 25+ signal generators filtered by regime detector
  ├─ trend/            EMA crossover, Supertrend, Donchian, MTF
  ├─ mean_reversion/   RSI, Bollinger, Z-score, VWAP
  ├─ breakout/         ATR squeeze, range breakout, S/R levels
  ├─ momentum/         MACD, volume momentum
  ├─ microstructure/   order book imbalance, cumulative delta, volume profile
  ├─ stat_arb/         pair trading (Kalman hedge ratio, ADF cointegration)
  ├─ volatility/       India VIX spike/reversal
  ├─ options/          gamma scalp, iron condor, theta decay, straddle, expiry
  ├─ institutional/    FII/DII flow signals
  ├─ gap/              GIFT Nifty pre-market gap
  ├─ corporate/        PEAD (post-earnings drift)
  └─ ml_based/         XGBoost / LightGBM / LSTM / TFT ensemble
      │
      ▼
 ml_models/          ← online learning + Bayesian hyperparameter optimisation
      │
      ▼
 execution_engine/   ← TWAP/VWAP smart orders → Upstox REST API
      │
      ▼
 risk_manager/       ← position sizing, stop-loss, CVaR, circuit breaker
 portfolio_manager/  ← beta-neutral hedging, factor decomposition
 analytics/          ← live P&L, auto-disable, Monte Carlo confidence intervals
 utils/              ← structured JSON logs, Telegram alerts, trade history
```

---

## Test Status

```
342 unit tests     — all passing
 60 live API tests — 59 pass, 1 skip (VWAP only available during market hours)
```

```bash
pytest tests/ -v                                        # offline tests
UPSTOX_ACCESS_TOKEN=<token> pytest tests/test_live_upstox.py -v   # live
```

---

## Architecture Summary

| Layer | Files | Key classes |
|---|---|---|
| Data | `data_engine/` | `UpstoxDataEngine`, `CircuitBreakerDetector`, `IndiaVIXMonitor` |
| Features | `feature_engine/` | `FeatureBuilder`, `AdvancedFeatureBuilder`, `Greeks` |
| Strategies | `strategies/` | `MetaStrategyEngine`, `BaseStrategy`, `Signal` |
| ML | `ml_models/` | `XGBoostModel`, `LSTMModel`, `TFT`, `AdaptiveModel`, `BayesianOptimizer` |
| Execution | `execution_engine/` | `TWAPOrder`, `VWAPOrder`, `UpstoxExecutor` |
| Risk | `risk_manager/` | `RiskManager`, `CVaRRiskManager` |
| Portfolio | `portfolio_manager/` | `PortfolioManager`, `BetaNeutralPortfolio` |
| Analytics | `analytics/` | `LivePnLTracker`, `FactorModel`, `run_monte_carlo()` |
| Alerts | `utils/` | `TelegramAlerter`, `get_logger()`, `TradeLogger` |
| Dashboard | `dashboard/` | Streamlit app on port 8501 |
