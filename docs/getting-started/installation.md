# Installation

This chapter takes you from a fresh checkout to a running dashboard. You can
install directly on your machine (recommended while developing) or run
everything in Docker (see [Deployment](../operations/deployment.md)).

## Requirements

| Component | Version | Needed for |
|---|---|---|
| Python | 3.11 or newer (developed on 3.14) | Everything |
| Node.js + npm | 18 or newer | Building and running the React dashboard |
| PostgreSQL | 16 (any recent version works) | MarketPulse pages: News, Signals, Watchlists, Alerts, Copilot, Portfolio Risk, Intraday Lab |
| Redis | 7 | Optional — provisioned by Docker Compose, not required by current code paths |
| Upstox account with API access | — | Real market data and trading. Without it the app runs on clearly labelled demo data |
| Telegram bot | — | Optional — trade and alert notifications |

The trading bot itself (`main.py`, `scripts/paper_trade.py`) does **not** need
PostgreSQL; it works from files in `data/` and `logs/`.

## Get the code and Python packages

```bash
git clone <your-repo-url> loony-trading
cd loony-trading
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` is grouped by purpose: core (numpy, pandas, PyYAML),
Upstox connectivity (`upstox-python-sdk`, `websockets`, `protobuf`), machine
learning (scikit-learn, XGBoost, LightGBM, hmmlearn), the dashboard (FastAPI,
uvicorn, APScheduler), persistence (SQLAlchemy, Alembic, psycopg2, redis), the
Anthropic SDK, `yfinance` for cross-asset features, and pytest.

Heavy optional packages are commented out at the bottom of the file — uncomment
them only if you need them:

| Package | Enables |
|---|---|
| `tensorflow` | The LSTM model (`ml_models/lstm_model.py`) |
| `stable-baselines3`, `gymnasium` | The reinforcement-learning agent |
| `ta-lib` | C-accelerated indicators (the built-in ones need nothing) |

## Configure your environment

All secrets live in `.env` at the repository root. Start from the template:

```bash
cp .env.example .env
```

The minimum for real market data is your Upstox app credentials:

```env
UPSTOX_API_KEY=your_api_key
UPSTOX_API_SECRET=your_api_secret
UPSTOX_REDIRECT_URI=http://localhost:3561/callback
```

Everything else is optional and documented in the
[Environment Variables](../reference/environment.md) reference. `.env` is in
`.gitignore` — never commit it.

Trading parameters live separately in `config/settings.yaml`, which is safe to
commit. Values written as `"${NAME}"` in that file are filled in from the
environment when it is loaded (`config/loader.py`), so secrets never have to be
typed into it. See the [Configuration Reference](../reference/configuration.md).

## Set up the database

MarketPulse stores stocks, news, signals, watchlists and alerts in PostgreSQL.
The connection string comes from `DATABASE_URL`, defaulting to
`postgresql+psycopg2://loony:loony@localhost:5432/loony_trading`.

The quickest way to get a matching database is the Compose service:

```bash
docker compose up -d db          # Postgres 16 on localhost:5432
```

Then create the schema with Alembic (it reads `DATABASE_URL` through
`db/base.py`):

```bash
alembic upgrade head
```

The migrations in `alembic/versions/` are, in order: the initial schema,
`NewsEvent.catalyst_score`, the alert-triggers table, historical-event
direction fields, and the `Signal.timeframe` column. Run `alembic upgrade head`
again after pulling new code. The tables are described in
[The Database](../marketpulse/database.md).

### Fill it with data

Pick one:

```bash
# Real data (needs an Upstox token — see the next chapter)
python scripts/backfill_stocks.py          # stock rows from the universe
python scripts/run_signal_engine.py        # composite signals for every stock

# Fully offline demo data (no keys at all)
python scripts/seed_demo_data.py
```

`seed_demo_data.py` loads the stock universe, scores signals on synthetic
prices through the real signal engine, ingests demo news and seeds demo
historical analogues. Every synthetic row is labelled — news text carries
`[DEMO DATA]` and historical events `[DEMO]` — so it can never be mistaken for
market data. Run it on an empty database: on a database with real signals it
would mix synthetic scores in.

## Install the dashboard frontend

```bash
cd dashboard/frontend
npm install
cd ../..
```

## Start the dashboard

```bash
bash dashboard/start.sh          # or: ./loony.sh start
```

Development mode starts two processes:

| Process | Address | Log |
|---|---|---|
| FastAPI backend (with auto-reload) | http://localhost:8000 | `logs/dashboard_backend.log` |
| Vite dev server (hot reload) | http://localhost:5163 | `logs/dashboard_frontend.log` |

Open **http://localhost:5163**. Vite proxies `/api` and `/ws` to the backend.
The interactive API explorer (Swagger) is at http://localhost:8000/api/docs.

For a single-process production build:

```bash
bash dashboard/start.sh --prod             # builds dist/, serves everything on :8000
bash dashboard/start.sh --prod --port 9000 # custom port
```

Stop everything with `bash dashboard/stop.sh` (add `--force` for `kill -9`).
The scripts keep PID files in `.pids/`; `stop.sh` falls back to killing
whatever listens on port 8000 and any `vite` process.

## Verify the installation

```bash
./loony.sh health                # full health check (token, packages, engine, files)
pytest tests/ -q --ignore=tests/test_live_upstox.py   # offline test suite
```

Both are described in [Command-Line Tools](../operations/cli.md) and
[Testing](../reference/testing.md). If the dashboard shows an amber
**DEMO DATA** banner, everything is installed correctly — it just has no
Upstox token yet. That is the subject of the next chapter.

## The `loony.sh` launcher

`./loony.sh` wraps the most common commands so you do not have to remember
script paths:

| Command | Runs |
|---|---|
| `start [--prod]`, `stop`, `restart` | `dashboard/start.sh` / `stop.sh` |
| `status` | Dashboard processes, paper bot freshness, token, last equity snapshot |
| `logs [--errors] [--n N] [file]` | Tails `logs/dashboard_backend.log` (or the given file) |
| `paper`, `signals`, `backtest`, `market` | `paper_trade.py`, `live_signals.py`, `backtest_runner.py`, `market_watch.py` |
| `train`, `tune` | `train_ml.py`, `tune_weights.py` |
| `health`, `report`, `journal` | `health.py`, `strategy_report.py`, `trade_journal.py` |
| `token [--refresh]` | `check_token.py`, or `upstox_login.py --force` |

Arguments after the command are passed through, e.g.
`./loony.sh paper --symbols RELIANCE,TCS --tick 30`. Trading commands first run
a token check and warn (but continue) if the token looks expired.
