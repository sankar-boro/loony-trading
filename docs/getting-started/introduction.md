# Introduction

Loony Trading is an algorithmic trading system for Indian markets (NSE/BSE),
trading through the [Upstox](https://upstox.com/developer/api-documentation/)
broker API. It researches, scores and — if you let it — trades equities, with
groundwork for F&O, all from one Python codebase and one web dashboard.

This handbook documents every part of it: what each feature does, how it
works inside, how to configure it, and how to operate it day to day.

> **Trading carries real financial risk.** Nothing in this software or this
> handbook is investment advice. Run everything in paper mode first, and read
> [The Trading Playbook](../operations/trading-playbook.md) before risking money.

## What the system does

At a high level, Loony Trading does five jobs:

| Job | What happens | Where in this book |
|---|---|---|
| **Collect data** | Historical candles, a live WebSocket price feed, news, India VIX, FII/DII flows, GIFT Nifty, corporate actions | Part III, chapters on market data |
| **Generate ideas** | 20+ rule-based strategies vote on every symbol; a composite engine scores each stock from news, technicals, momentum and history | Strategies chapters; [Composite Signals](../marketpulse/composite-signals.md) |
| **Manage risk** | Position sizing, stop-losses, trailing stops, drawdown limits, one position per symbol, F&O lot sizes | [Risk Management](../engine/risk-management.md) |
| **Execute** | Paper fills with realistic NSE charges, or real orders through Upstox; intraday squareoff; crash recovery; broker reconciliation | [Execution](../engine/execution.md), [Position Safety](../engine/position-safety.md) |
| **Show you** | A React dashboard with charts, positions, P&L, signals, alerts, an AI copilot, backtests — and this handbook | Part II |

## The two halves of the codebase

The project grew in two stages, and it helps to know which half you are
looking at.

**1. The trading bot** (`main.py`, `scripts/paper_trade.py` and the engine
packages). This is the part that watches prices and trades. It loads history,
runs every enabled strategy through the `MetaStrategyEngine`, sizes positions
with the `RiskManager`, and sends orders through the `UpstoxExecutor` — or
simulates them in paper mode. It works from files on disk (`data/`, `logs/`)
and needs no database.

**2. MarketPulse AI** (`signals/`, `db/`, `ai/`, `data_engine/news/`,
`scheduler/`). This is the research layer behind most dashboard pages. It
ingests and classifies news, scores every stock with a composite signal
(catalyst, technical, momentum, volume, historical analogues), answers "why is
this stock moving?", evaluates your alerts, and runs it all on a schedule. It
stores everything in **PostgreSQL**. It never places orders.

The dashboard (`dashboard/`) sits on top of both: a FastAPI backend that reads
the bot's files and the MarketPulse database, and a React frontend.

## Architecture at a glance

```
                     ┌──────────────── Upstox API ────────────────┐
                     │  OAuth · historical candles · WebSocket    │
                     │  feed · orders · positions · holdings      │
                     └───────┬───────────────────────┬────────────┘
                             │                       │
  NSE / GIFT Nifty / VIX ─┐  ▼                       ▼
  NewsAPI ───────────┐    │  data_engine/  ───►  execution_engine/
                     │    │  (candles, feed,      (paper fills, real orders,
                     │    │   live bars)           charges, reconciliation)
                     │    ▼        │                       ▲
                     │  feature_engine/ (indicators,       │
                     │     40+ features, Greeks)           │
                     │             │                       │
                     │             ▼                       │
                     │  strategies/ ─► MetaStrategyEngine ─► risk_manager/
                     │  (20+ strategies, regime filter)    (sizing, stops)
                     │
                     ▼
     data_engine/news ─► signals/ (composite score, alerts, why, copilot)
                              │          ▲
                              ▼          │ scheduler/ (APScheduler jobs)
                         PostgreSQL ◄────┘
                              │
   data/*.json, logs/*.jsonl  │
              │               ▼
              └────────► dashboard/backend (FastAPI :8000)
                                  │
                                  ▼
                        dashboard/frontend (React)
```

## Package map

| Package | Responsibility | Chapter |
|---|---|---|
| `main.py` | The live/paper trading bot, backtest and train entry points | [Architecture of the Bot](../engine/architecture.md) |
| `config/` | `settings.yaml`, the settings loader, the stock universe | [Configuration Reference](../reference/configuration.md) |
| `data_engine/` | Upstox auth, instruments, candles, live feed, NSE data, VIX, GIFT Nifty, news | [Market Data](../engine/market-data.md) and following |
| `feature_engine/` | Indicators, feature builder, Greeks, candlestick patterns | [Features and Indicators](../engine/features.md) |
| `strategies/` | All strategies, regime detection, the meta engine | [The Strategy Framework](../engine/strategy-framework.md) |
| `risk_manager/` | Position sizing, stops, lot sizes, CVaR | [Risk Management](../engine/risk-management.md) |
| `execution_engine/` | Upstox executor, charges, smart orders, reconciliation | [Execution](../engine/execution.md) |
| `portfolio_manager/`, `analytics/` | Portfolio metrics, beta hedging, factor model, live P&L | [Portfolio and Analytics](../engine/portfolio-analytics.md) |
| `ml_models/` | Training data, XGBoost/LightGBM ensemble, other models | [Machine Learning](../engine/machine-learning.md) |
| `backtester/` | Event-driven backtests, walk-forward, Monte Carlo, stress tests | [Backtesting](../engine/backtesting.md) |
| `signals/`, `db/`, `ai/` | MarketPulse composite signals, database, LLM client | Part IV |
| `scheduler/` | Background jobs | [The Scheduler](../marketpulse/scheduler.md) |
| `scripts/` | Command-line tools | [Command-Line Tools](../operations/cli.md) |
| `dashboard/` | FastAPI backend + React frontend | Part II |
| `utils/` | Logging, time helpers, Telegram, Kalman filter | [Notifications](../operations/notifications.md), [Logs and Data Files](../operations/logs-and-data-files.md) |

## Modes of operation

| Mode | Command | Real money? | Notes |
|---|---|---|---|
| Demo | dashboard with no Upstox token | No | Synthetic, clearly labelled data so every page works offline |
| Paper (standalone) | `python scripts/paper_trade.py` | No | Polls real prices, virtual portfolio, feeds the dashboard |
| Paper (bot) | `python main.py --mode paper` | No | The full live bot with simulated fills |
| Live | `python main.py --mode live` | **Yes** | Real orders through Upstox |
| Backtest | `python main.py --mode backtest`, `scripts/backtest_runner.py`, Strategy Lab page | No | Historical simulation |
| Train | `python scripts/train_ml.py` | No | Trains the ML model, saved only if it beats naive baselines |

[Your First Session](first-session.md) walks through the safe order to try them in.

## How to read this book

- **Part I — Getting Started**: install, connect Upstox, run your first session.
- **Part II — The Dashboard**: every page, what it shows and where the data comes from.
- **Part III — The Trading Engine**: how the bot thinks — data, features,
  every strategy, risk, execution, ML and backtesting.
- **Part IV — MarketPulse AI**: the research layer — news, composite
  signals, alerts, copilot, scheduler.
- **Part V — Operations**: scripts, paper trading, notifications, files,
  deployment, the daily playbook, troubleshooting.
- **Part VI — Reference**: every configuration key, environment variable and
  REST endpoint; testing; glossary.
- **Appendices**: the project status checklist and the intraday audit.

Use the search box at the top of the table of contents to find any term
across the whole handbook.

## Conventions

- Paths like `strategies/meta_engine.py` are relative to the repository root.
- Configuration keys are written as dotted paths into `config/settings.yaml`,
  e.g. `risk.max_risk_per_trade`.
- Times are **IST** (Asia/Kolkata) unless stated otherwise. The NSE equity
  session runs 09:15–15:30 IST.
- Money is in rupees (₹). Quantities are shares (equity) or units (F&O, always
  a multiple of the lot size).
