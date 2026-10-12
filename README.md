# Loony Trading

Algorithmic trading and market research for Indian equities (NSE/BSE) through
the Upstox API: a trading bot with 20+ strategies, risk management and
paper/live execution, plus **MarketPulse AI** — news classification, composite
stock scores, alerts and an evidence-grounded copilot — all behind a React
dashboard.

> Trading carries real financial risk. Nothing here is investment advice.
> Paper trade first.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env                  # Upstox API key/secret (optional: Telegram, NewsAPI, Anthropic)
cd dashboard/frontend && npm install && cd ../..
./loony.sh start                      # dashboard → http://localhost:5163
python scripts/upstox_login.py        # daily Upstox token (the app runs on demo data without one)
python scripts/paper_trade.py         # paper trading — no real orders
```

## The handbook

Complete documentation lives in [`docs/`](docs/) as a book, and is readable in
the dashboard under **Docs** (`/docs`), with a table of contents and search.

| Part | Covers |
|---|---|
| [I. Getting Started](docs/getting-started/introduction.md) | What the system is, installation, Upstox tokens, your first session |
| [II. The Dashboard](docs/dashboard/overview.md) | Every page and where its data comes from |
| [III. The Trading Engine](docs/engine/architecture.md) | The bot, market data, features, every strategy, risk, execution, position safety, ML, backtesting |
| [IV. MarketPulse AI](docs/marketpulse/overview.md) | Database, news pipeline, composite signals, analogues, copilot, alerts, scheduler |
| [V. Operations](docs/operations/cli.md) | Command-line tools, paper trading, notifications, files, deployment, playbook, troubleshooting |
| [VI. Reference](docs/reference/configuration.md) | Every configuration key, environment variable and API endpoint; testing; glossary |
| [Appendices](docs/appendix/status.md) | Project status checklist and the intraday audit |

The table of contents is [`docs/book.yaml`](docs/book.yaml).

## Layout

| Path | Contents |
|---|---|
| `main.py` | Trading bot (paper/live), backtest, train and auth entry points |
| `config/` | `settings.yaml`, settings loader, stock universe |
| `data_engine/` | Upstox auth, instruments, candles, live feed, NSE data, news |
| `feature_engine/` | Indicators, feature builder, Greeks, patterns |
| `strategies/` | Strategies, regime detection, meta engine |
| `risk_manager/`, `execution_engine/`, `portfolio_manager/`, `analytics/` | Risk, orders, portfolio analysis |
| `ml_models/`, `backtester/` | ML pipeline, backtesting, Monte Carlo, stress tests |
| `signals/`, `db/`, `ai/`, `scheduler/` | MarketPulse AI |
| `dashboard/` | FastAPI backend + React frontend |
| `scripts/` | Command-line tools |
| `tests/` | Offline and live test suites |

## Tests

```bash
pytest tests/ -q --ignore=tests/test_live_upstox.py           # offline
UPSTOX_ACCESS_TOKEN=<token> pytest tests/test_live_upstox.py  # live API
```
