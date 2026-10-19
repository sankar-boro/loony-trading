# Command-Line Tools

Everything in `scripts/` runs from the repository root as
`python scripts/<name>.py`; the most common ones also have `./loony.sh`
shortcuts. Scripts that need market data look for a token in this order:
`--token`, `UPSTOX_ACCESS_TOKEN`, then `data/upstox_token.json` (if it has
not passed its 03:30 IST expiry).

## At a glance

| Task | Script | `loony.sh` |
|---|---|---|
| Log in to Upstox | `upstox_login.py` | `token --refresh` |
| Check tokens | `check_token.py` | `token` |
| Renew token from cron | `auto_login.sh` | — |
| TOTP codes | `generate_totp.py` | — |
| Health check | `health.py` | `health` |
| One-screen status | `status.py` | (`status` is similar) |
| Verify the Upstox API | `test_upstox.py` | — |
| Download the instrument master | `fetch_instruments.sh` | — |
| Scan for signals | `live_signals.py` | `signals` |
| Live prices | `market_watch.py` | `market` |
| Option chain | `option_chain.py` | — |
| Account: holdings, positions, funds | `portfolio.py` | — |
| Place / cancel orders by hand | `order.py` | — |
| Paper trade | `paper_trade.py` | `paper` |
| Backtest | `backtest_runner.py` | `backtest` |
| Find cointegrated pairs | `find_pairs.py` | — |
| Fit regime models | `fit_regimes.py` | — |
| Tune strategy weights | `tune_weights.py` | `tune` |
| Train the ML model | `train_ml.py` | `train` |
| Trade journal | `trade_journal.py` | `journal` |
| Strategy report | `strategy_report.py` | `report` |
| Daily P&L report | `daily_report.py` | — |
| Execution quality | `execution_report.py` | — |
| MarketPulse: load stocks | `backfill_stocks.py` | — |
| MarketPulse: score signals | `run_signal_engine.py` | — |
| MarketPulse: signal track record | `evaluate_signals.py` | — |
| MarketPulse: historical analogues | `backfill_historical_events.py` | — |
| Demo data (database) | `seed_demo_data.py` | — |
| Load the handbook into Postgres | `migrate_docs.py` | — |
| Sample dashboard files | `seed_dashboard_data.py` | — |

## Access and diagnostics

### upstox_login.py

```bash
python scripts/upstox_login.py [--force] [--no-browser] [--port 3561] [--env .env]
python scripts/upstox_login.py --token-request     # approve on your phone
python scripts/upstox_login.py --sandbox           # paste a sandbox token
```

Browser OAuth by default. Saves `data/upstox_token.json` (and an extended
token if Upstox returns one). See [Connecting to Upstox](../getting-started/upstox-access.md).

### check_token.py

`[--token T] [--sandbox] [--extended] [--all]` — decodes the token's JWT
expiry, reports which source it came from and fetches a few live prices to
prove it works.

### auto_login.sh

`[--check-only | --force | --paste-token]` — renews the daily token only if it
has expired (cron-friendly). Edit `VENV_PATH` and `SERVICE_NAME` at the top.

### generate_totp.py

`[--secret S] [--save] [--live] [--show-next]` — prints the current 6-digit
TOTP code (and the next one with `--show-next`); `--live` refreshes every 30 s;
`--save` remembers the secret locally.

### health.py

`[--quiet] [--fix]` — checks, section by section: the token and a live price
fetch, the dashboard API, the strategy engine and feature builder, the ML model
files, the data files (`live_positions.json`, `equity_curve.jsonl`,
`daily_pnl.jsonl`, `paper_trades.jsonl`, `settings.yaml`), required Python
packages, log sizes and free disk space. `--quiet` shows only failures; `--fix`
attempts simple repairs.

### status.py

`[--watch N]` — market status, token, bot freshness, open positions and today's
P&L on one screen; refreshes every N seconds with `--watch`.

### test_upstox.py

`[--token T] [--verbose] [--market-only] [--sandbox] [--env FILE]` — about 20
numbered checks against the real API: auth, profile, LTP, full quotes,
historical and intraday candles for several intervals (this is how you find out
whether 5/15-minute candles work on your account), the instrument master, funds,
positions, orders and the WebSocket feed. `--market-only` skips account
endpoints.

### fetch_instruments.sh

`bash scripts/fetch_instruments.sh [NSE|BSE]` — downloads the Upstox instrument
master to `data/instruments/<EXCHANGE>.csv` (and `.xlsx`). Needed by
`tests/test_instrument_isins.py`, which checks the universe's ISINs.

## Market tools

### live_signals.py

```bash
python scripts/live_signals.py [--symbols A,B] [--refresh SEC] [--timeframe 1d|1h|15m]
       [--days N] [--buy-only|--sell-only] [--min-confidence X] [--all-signals]
       [--no-features] [--token T]
```

Runs the strategy engine on each symbol and prints the best signal (confidence
× weight) with stop, target, regime and per-strategy confidences. Telegram
alerts are sent for new signals when configured.

### market_watch.py

`[--interval SEC] [--instruments A,B] [--indices-only] [--no-clear] [--token T]`
— a refreshing terminal table of prices, change, OHLC and depth.

### option_chain.py

`[--symbol "Nifty 50"] [--expiry YYYY-MM-DD] [--strikes N] [--weekly]
[--refresh SEC] [--list-expiries] [--token T]` — call/put LTP, OI, IV and
volume around the ATM strike, with PCR and max pain.

### portfolio.py

`[--holdings-only|--positions-only|--funds-only] [--refresh SEC] [--token T]` —
your Upstox account: holdings with P&L, today's positions, available margin.

### order.py

```bash
python scripts/order.py                 # interactive menu
python scripts/order.py place           # guided order entry
python scripts/order.py orders | history | trades
python scripts/order.py cancel <order_id>
python scripts/order.py --sandbox ...   # against the sandbox
```

Places **real orders** unless `--sandbox`. Asks for confirmation before
sending.

## Trading and research

### paper_trade.py

```bash
python scripts/paper_trade.py [--symbols A,B] [--capital 500000] [--tick 60]
       [--signal-every 5] [--max-positions 5] [--risk-per-trade 0.01]
       [--timeframe 1d] [--log-file FILE] [--token T]
```

See [Paper Trading](paper-trading.md).

### backtest_runner.py

```bash
python scripts/backtest_runner.py [--symbol S | --symbols A,B] [--days 365]
       [--capital 500000] [--timeframe 1d] [--source upstox|recorded]
       [--product CNC|MIS] [--strategies a,b]
       [--monte-carlo] [--walk-forward] [--trades] [--equity-curve] [--token T]
```

`--source recorded` backtests on the 1-minute bars the live bot saved to
`data/live_bars/` (timeframes `1m` to `1h`, no token needed).

See [Backtesting](../engine/backtesting.md).

### find_pairs.py

`[--sectors A,B] [--symbols A,B] [--days 365] [--top 25] [--backtest]` —
tests every same-sector pair for cointegration and half-life, optionally
backtests the tradable ones, and prints a `strategies.pairs` block. See
[Finding pairs](../engine/strategies-stat-arb.md#finding-pairs).

### fit_regimes.py

`[--symbols A,B] [--all] [--days 1095]` — fits and gates the per-symbol HMM
regime models (default: Nifty 50 stocks plus NIFTY50 and BANKNIFTY) and
prints which are usable. See
[The HMM detector](../engine/strategy-framework.md#the-hmm-detector).

### tune_weights.py

`[--symbols A,B] [--days 365] [--min-sharpe 0.0] [--dry-run] [--token T]` —
backtests each strategy separately and writes weights to `settings.yaml`. See
[Backtesting](../engine/backtesting.md#tuning-strategy-weights).

### train_ml.py

`[--symbols A,B] [--days 730] [--enable] [--save-anyway] [--token T]` — gated ML
training. See [Machine Learning](../engine/machine-learning.md#training).

## Reports

### trade_journal.py

```bash
python scripts/trade_journal.py [--days N] [--live] [--symbol S] [--strategy NAME]
       [--winners] [--by-strategy] [--by-symbol] [--export trades.csv]
```

Lists closed trades from `logs/paper_trades.jsonl` (or `logs/trades.jsonl`
with `--live`), filters them, groups P&L by strategy or symbol, and exports CSV.

### strategy_report.py

`[--file PATH] [--days N] [--min-trades N] [--sort FIELD] [--csv]` — per-strategy
trades, win rate, total and average P&L, profit factor, from the paper log by
default.

### daily_report.py

`[--days N | --all] [--csv [FILE]]` — the daily records in
`data/daily_pnl.jsonl` with totals, Sharpe and win rate.

## MarketPulse data

| Command | Does |
|---|---|
| `python scripts/backfill_stocks.py` | Upsert the universe into the `stocks` table |
| `python scripts/run_signal_engine.py [--limit N] [--lookback-days 200] [--timeframe 1d]` | Score and store composite signals |
| `python scripts/evaluate_signals.py [--days 90] [--report-only]` | Record outcomes of past signals and print the track record |
| `python scripts/backfill_historical_events.py [--min-age-days 7]` | Build analogues from matured news events |
| `python scripts/backfill_historical_events.py --seed-demo TYPE [--seed-count 40] [--seed-symbol RELIANCE]` | Synthetic `[DEMO]` analogues |
| `python scripts/seed_demo_data.py [--symbols A,B] [--days N]` | Full offline demo database |
| `python scripts/seed_dashboard_data.py` | 180-day backtest of five stocks written as the dashboard's file data (positions, trades, equity, daily P&L) |
| `python scripts/migrate_docs.py [--tables-only] [--write-sql]` | Create the `doc_chapters` / `doc_sections` tables from `db/sql/handbook.sql` in `DB_SCHEMA`, then load `docs/` into them; `--write-sql` regenerates the SQL from the models. See [The Database](../marketpulse/database.md#the-handbook) |
