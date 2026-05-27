# Loony Trading Bot

A fully automated, production-grade trading bot integrating all major strategies with ML-driven regime detection and dynamic strategy selection.

## Quick Start

```bash
# 1. Clone and install
pip install -r requirements.txt

# 2. Configure API keys
cp .env.example .env
# edit .env with your exchange credentials

# 3. Paper trade (default)
python main.py

# 4. Run backtests
python main.py --mode backtest

# 5. Train ML models
python main.py --mode train

# 6. Launch dashboard
streamlit run dashboard/app.py
```

## Docker

```bash
cp .env.example .env      # fill in credentials
docker compose up -d      # starts bot + dashboard on port 8501
```

## Architecture

```
loony-trading/
├── config/               # YAML settings + env-var loader
├── data_engine/          # OHLCV ingestion (historical + WebSocket)
│   ├── market_data.py    # ccxt multi-exchange, parquet caching
│   ├── orderbook.py      # L2 order book tracker
│   └── sentiment.py      # NewsAPI + VADER sentiment
├── feature_engine/
│   ├── indicators.py     # 20+ indicators (no ta-lib dependency)
│   ├── feature_builder.py# Multi-timeframe feature matrix
│   └── pattern_detector.py # Candlestick + chart patterns
├── strategies/
│   ├── base.py           # BaseStrategy, Signal, SignalType
│   ├── regime_detector.py# ADX + volatility market regime
│   ├── meta_engine.py    # Orchestrates all strategies, blends signals
│   ├── trend/            # EMA crossover, MTF trend, Supertrend, Donchian
│   ├── mean_reversion/   # RSI, Bollinger, Z-score, VWAP
│   ├── breakout/         # S/R breakout, ATR volatility, range breakout
│   ├── momentum/         # MACD, RSI momentum, volume momentum
│   ├── microstructure/   # Order book imbalance + whale detection
│   ├── stat_arb/         # Pair trading (cointegration + rolling hedge)
│   ├── candlestick/      # Pattern detection strategy
│   └── ml_based/         # ML model wrapper strategy
├── ml_models/
│   ├── xgb_model.py      # XGBoost classifier
│   ├── lgbm_model.py     # LightGBM classifier
│   ├── lstm_model.py     # LSTM/GRU (TensorFlow)
│   ├── ensemble.py       # Soft-voting ensemble
│   ├── rl_agent.py       # PPO reinforcement learning agent
│   └── trainer.py        # Feature extraction + training orchestration
├── risk_manager/
│   └── risk_manager.py   # Position sizing, trailing stops, drawdown guard
├── execution_engine/
│   └── executor.py       # Smart order routing, slippage, retry, paper/live
├── portfolio_manager/
│   └── portfolio.py      # Multi-asset allocation, correlation guard
├── backtester/
│   └── backtester.py     # Event-driven backtester + walk-forward validation
├── dashboard/
│   └── app.py            # Streamlit UI (charts, signals, metrics)
├── utils/                # Logger, math, notifier, trade logger
├── tests/                # 24 unit tests (all passing)
├── main.py               # Entry point
├── Dockerfile
└── docker-compose.yml
```

## Strategies Implemented

| Category | Strategies |
|----------|-----------|
| **Trend** | EMA crossover, Multi-timeframe alignment, Supertrend, Donchian breakout |
| **Mean Reversion** | RSI, Bollinger Bands, Z-score, VWAP |
| **Breakout** | Support/Resistance, ATR volatility squeeze, Asian session range |
| **Momentum** | MACD, RSI-50 cross, Volume momentum |
| **Microstructure** | Order book imbalance, Whale pressure |
| **Statistical Arb** | Pair trading (rolling hedge ratio) |
| **Price Action** | Candlestick patterns (engulfing, doji, hammer, stars) + chart patterns (H&S, double top/bottom) |
| **Machine Learning** | XGBoost, LightGBM, LSTM ensemble |
| **Reinforcement Learning** | PPO agent (stable-baselines3, optional) |
| **Sentiment** | NewsAPI + VADER NLP scoring |

## Key Features

- **Regime Detection**: Automatically classifies market as trending/ranging/volatile and routes signals to appropriate strategies
- **Walk-Forward Validation**: Prevents overfitting in backtests
- **Kelly Criterion**: Optional fractional Kelly position sizing
- **Trailing Stops**: ATR-adjusted trailing stops on all positions
- **Correlation Guard**: Blocks new trades correlated with existing positions
- **Pair Trading**: Rolling hedge ratio with z-score entry/exit
- **Async Architecture**: `asyncio` event loop — non-blocking data + execution

## Configuration

All settings in `config/settings.yaml`. Key parameters:

| Setting | Default | Description |
|---------|---------|-------------|
| `system.mode` | `paper` | `paper` / `live` / `backtest` |
| `risk.max_risk_per_trade` | `0.01` | 1% capital per trade |
| `risk.max_daily_drawdown` | `0.05` | 5% daily loss limit |
| `risk.max_concurrent_trades` | `10` | Max open positions |
| `portfolio.initial_capital` | `10000` | Starting capital (USDT) |

## Running Tests

```bash
pytest tests/ -v
```

## Deployment (Cloud)

```bash
# AWS / GCP — deploy with Docker
docker build -t loony-trading .
docker run -d --env-file .env -p 8501:8501 loony-trading

# Or use docker compose
docker compose up -d
```
