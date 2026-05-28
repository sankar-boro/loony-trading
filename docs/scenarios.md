# App Testing Scenarios

Manual testing guide for every runnable component of Loony Trading.
Covers the dashboard, paper trading, backtest, and all CLI scripts.

---

## Prerequisites

### 1. Token check

Before anything else, confirm your Upstox token is valid:

```bash
python scripts/check_token.py
```

Expected output:

```
Token age   : 5.2h  (valid for 17.8h more)
Token source: data/upstox_token.json
Market      : CLOSED  (next open: Wednesday 2026-05-28 09:15 IST)
```

If the token is expired (> 23h old), renew it:

```bash
python scripts/upstox_login.py
```

### 2. Environment

```bash
# Verify .env is loaded and key vars are set
python -c "
import os; from pathlib import Path
for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k = line.split('=')[0].strip()
        print(k, '=', 'SET' if os.environ.get(k) or line.split('=',1)[1].strip() else 'MISSING')
"
```

---

## Scenario 1 — Dashboard

The dashboard has two processes: a FastAPI backend (port 8000) and a Vite dev server (port 5173).

### Start (development mode)

```bash
bash dashboard/run_dev.sh
```

Then open **http://localhost:5173** in your browser.

### Start (production — single port)

```bash
bash dashboard/run_prod.sh   # builds frontend, serves everything on :8000
```

Open **http://localhost:8000**.

### Pages and what to test

| Page       | URL           | Works without bot running? | What to verify                                                         |
| ---------- | ------------- | -------------------------- | ---------------------------------------------------------------------- |
| Dashboard  | `/`           | Partial                    | KPI cards show `—` when no data; equity chart empty                    |
| Chart      | `/chart`      | **Yes**                    | Pick RELIANCE → select 1D interval → candles load                      |
| Positions  | `/positions`  | Partial                    | Empty table; signal log empty                                          |
| Trades     | `/trades`     | Partial                    | Empty until paper trades close                                         |
| Daily P&L  | `/daily`      | Partial                    | Empty until EOD report runs                                            |
| Strategies | `/strategies` | **Yes**                    | Weight bars load from `/api/config`                                    |
| Backtest   | `/backtest`   | **Yes**                    | Pick RELIANCE, 6 months, ema_crossover → Run Backtest → result appears |

### API endpoints (verify directly)

```bash
# All endpoints — open in browser or curl:
curl http://localhost:8000/api/status       | python -m json.tool
curl http://localhost:8000/api/config       | python -m json.tool
curl http://localhost:8000/api/positions    | python -m json.tool
curl http://localhost:8000/api/equity       | python -m json.tool
curl http://localhost:8000/api/trades       | python -m json.tool
curl http://localhost:8000/api/daily        | python -m json.tool

# Chart data (OHLCV)
curl "http://localhost:8000/api/chart/RELIANCE?interval=day&days=60" | python -m json.tool

# Live LTP
curl "http://localhost:8000/api/ltp?symbols=RELIANCE,TCS,NIFTY50" | python -m json.tool

# Swagger docs
open http://localhost:8000/api/docs
```

### Backtest via API

```bash
# Submit single-symbol backtest job
curl -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{"symbol":"RELIANCE","strategy":"bollinger_reversion","days":365,"capital":500000}'

# Submit batch backtest job using symbols list
curl -X POST http://localhost:8000/api/backtest/batch \
  -H "Content-Type: application/json" \
  -d '{"symbols":["RELIANCE","TCS"],"strategies":["ema_crossover","rsi_mean_reversion"],"days":180,"capital":500000,"benchmark":true}'

# Submit walk-forward backtest
curl -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{"symbol":"RELIANCE","strategies":["ema_crossover"],"walk_forward":true,"walk_forward_splits":5}'

# Optional explicit token override
curl -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{"symbol":"RELIANCE","strategy":"bollinger_reversion","token":"YOUR_UPSTOX_TOKEN"}'

# Poll result (replace JOB_ID)
curl http://localhost:8000/api/backtest/JOB_ID | python -m json.tool
```

---

## Scenario 2 — Paper Trading

Simulates a live trading session using real Upstox prices. No real orders are placed.

### Quick smoke test (works outside market hours)

```bash
# Fast ticks to verify the full loop fires
python scripts/paper_trade.py \
  --symbols RELIANCE,TCS,HDFCBANK \
  --tick 5 \
  --signal-every 1 \
  --max-positions 3
```

What to look for:

- "Strategy engine ready — 17 strategies" on startup
- Historical data loads: `RELIANCE: 446 bars OK`
- Signals fire within the first few ticks (e.g., `SELL 93 × RELIANCE @ ₹1,350.50`)
- `data/live_positions.json` is created/updated
- `data/equity_curve.jsonl` gets a new line each tick

### Full session (during market hours: 9:15 AM – 3:30 PM IST)

```bash
python scripts/paper_trade.py \
  --symbols RELIANCE,TCS,HDFCBANK,SBIN,AXISBANK \
  --capital 500000 \
  --tick 30 \
  --signal-every 3 \
  --max-positions 5
```

### With 15-minute intraday data

```bash
python scripts/paper_trade.py \
  --symbols RELIANCE,TCS \
  --timeframe 15m \
  --tick 15 \
  --signal-every 1
```

### Key files written during a session

| File                       | Contents                                     | Used by                    |
| -------------------------- | -------------------------------------------- | -------------------------- |
| `data/live_positions.json` | Open positions, cash, signal log             | Dashboard `/api/positions` |
| `data/equity_curve.jsonl`  | One line per tick: `{ts, equity, cash, ...}` | Dashboard `/api/equity`    |
| `data/daily_pnl.jsonl`     | One line per EOD (3:35 PM): daily stats      | Dashboard `/api/daily`     |
| `logs/paper_trades.jsonl`  | Every closed trade with full detail          | Dashboard `/api/trades`    |

### After running the bot, verify the dashboard shows live data

1. Start the dashboard (`bash dashboard/run_dev.sh`)
2. Open **http://localhost:5173**
3. Dashboard page → equity curve and KPIs should populate
4. Positions page → open positions and signal log visible
5. Trades page → closed trades table (if any trades closed)

---

## Scenario 3 — Backtest

Run the event-driven backtester on historical Upstox data.

### Basic run — top 5 Nifty50 stocks

```bash
python scripts/backtest_runner.py
```

### Single symbol with equity curve

```bash
python scripts/backtest_runner.py --symbol RELIANCE --days 730 --equity-curve
```

### Multiple symbols

```bash
python scripts/backtest_runner.py \
  --symbols RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK,SBIN \
  --days 730
```

### Specific strategies only

```bash
python scripts/backtest_runner.py \
  --symbols RELIANCE,TCS \
  --strategies bollinger_reversion,vwap_reversion,rsi_momentum
```

### With full trade log

```bash
python scripts/backtest_runner.py --symbol RELIANCE --trades --equity-curve
```

### Walk-forward validation (anti-overfitting check)

```bash
python scripts/backtest_runner.py --symbol RELIANCE --walk-forward
```

### Monte Carlo tail risk (requires trades to have run)

```bash
python scripts/backtest_runner.py --symbol RELIANCE --monte-carlo
```

### What to check in the output

- **Total Return** vs Nifty 50 benchmark return (was strategy alpha positive?)
- **Sharpe Ratio** — above 1.0 is good, above 2.0 is excellent
- **Max Drawdown** — should be < 15% for a healthy strategy
- **Profit Factor** — above 1.0 means more wins than losses by value
- **Strategy Breakdown** — which strategies contributed most P&L

---

## Scenario 4 — Strategy Weight Tuning

Backtests each strategy individually and writes Sharpe-proportional weights to `config/settings.yaml`.

### Dry run — preview without writing

```bash
python scripts/tune_weights.py --dry-run --days 730
```

### Tune with a minimum Sharpe filter

```bash
# Only enable strategies with median Sharpe > 0.3
python scripts/tune_weights.py --days 730 --min-sharpe 0.3

# More permissive — keep anything above zero
python scripts/tune_weights.py --days 730 --min-sharpe 0.0
```

### On a specific symbol set

```bash
python scripts/tune_weights.py \
  --symbols RELIANCE,TCS,SBIN \
  --days 365 \
  --dry-run
```

### Verify settings were updated

```bash
grep -A 20 "^strategies:" config/settings.yaml
```

---

## Scenario 5 — Live Signal Scanner

Generates signals from real Upstox data without placing any trades.

```bash
# Default symbols
python scripts/live_signals.py

# Specific symbols
python scripts/live_signals.py --symbols RELIANCE,TCS,HDFCBANK,NIFTY50,BANKNIFTY
```

Best run during market hours — prices are live. Outside market hours it uses the last close.

---

## Scenario 6 — Market Watch

Live price ticker for any set of symbols.

```bash
python scripts/market_watch.py

python scripts/market_watch.py --symbols RELIANCE,TCS,HDFCBANK,NIFTY50,BANKNIFTY,INFY
```

---

## Scenario 7 — Option Chain

Live options chain with Greeks and IV.

```bash
python scripts/option_chain.py --symbol NIFTY
python scripts/option_chain.py --symbol BANKNIFTY
python scripts/option_chain.py --symbol RELIANCE
```

Best run during market hours (9:15 AM – 3:30 PM IST). Outside hours the chain may be stale.

---

## Scenario 8 — Trade Journal & Reports

### View paper trade history

```bash
python scripts/trade_journal.py
```

Reads `logs/paper_trades.jsonl`. Works after any paper trading session has closed at least one trade.

### Daily P&L report

```bash
python scripts/daily_report.py
```

Reads `data/daily_pnl.jsonl`. Populated at 3:35 PM each day the bot runs.

### Portfolio snapshot

```bash
python scripts/portfolio.py
```

Reads `data/live_positions.json`. Shows current open positions and P&L.

---

## Scenario 9 — Full API Test Suite

```bash
# 20 tests covering auth, LTP, OHLCV, historical candles, WebSocket protobuf
python scripts/test_upstox.py
```

This script runs sequentially and prints pass/fail for each section:

| Section             | Tests                 | Notes                      |
| ------------------- | --------------------- | -------------------------- |
| Token validation    | Auth header, expiry   | Fails if token > 23h       |
| LTP fetch           | Single + bulk         | Empty outside market hours |
| Full quote          | OHLC + bid/ask        | Empty outside market hours |
| Historical daily    | 30d / 365d / 2y       | Works anytime              |
| Historical intraday | 15m / 60m candles     | Works anytime              |
| Instrument search   | RELIANCE, TCS, HDFC   | Works anytime              |
| WebSocket feed      | Binary protobuf frame | Requires market hours      |

---

## Scenario 10 — Token Management

### Check current token

```bash
python scripts/check_token.py
```

### Refresh token (opens browser OAuth flow)

```bash
python scripts/upstox_login.py
# Follow browser prompt, paste redirect URL
```

### Force refresh even if token is valid

```bash
python scripts/upstox_login.py --force
```

### Generate TOTP (if using TOTP-based login)

```bash
python scripts/generate_totp.py
```

---

## Recommended Test Sequence

### First-time setup check (5 minutes)

```bash
python scripts/check_token.py
python scripts/backtest_runner.py --symbol RELIANCE --days 180 --equity-curve
python scripts/live_signals.py --symbols RELIANCE,TCS,SBIN
```

### Before market open (9:00–9:15 AM IST)

```bash
# Quick smoke test — verify bot starts cleanly
python scripts/paper_trade.py --tick 5 --signal-every 1 --max-positions 2
# Ctrl+C after a few ticks

# Start dashboard
bash dashboard/run_dev.sh
```

### During market hours (9:15 AM–3:30 PM IST)

```bash
# Full paper trading session in a separate terminal
python scripts/paper_trade.py \
  --symbols RELIANCE,TCS,HDFCBANK,SBIN,AXISBANK \
  --capital 500000 \
  --tick 30 \
  --signal-every 3

# In another terminal — watch live signals
python scripts/market_watch.py --symbols RELIANCE,TCS,HDFCBANK,NIFTY50
```

### After market close (after 3:35 PM IST)

```bash
python scripts/trade_journal.py
python scripts/daily_report.py
python scripts/tune_weights.py --days 730 --min-sharpe 0.3 --dry-run
```

---

## Troubleshooting

| Symptom                         | Cause                            | Fix                                                                 |
| ------------------------------- | -------------------------------- | ------------------------------------------------------------------- |
| `No token found`                | Token file missing or expired    | `python scripts/upstox_login.py`                                    |
| `FeatureBuilder returns 0 rows` | Fetching < 200 days of data      | Use `--days 730` or `--days 365` minimum                            |
| `Strategy engine load failed`   | Import error in a strategy       | `python -c "from strategies.meta_engine import MetaStrategyEngine"` |
| Dashboard shows empty data      | Bot has never run                | Run `paper_trade.py` first to create data files                     |
| LTP returns `{}`                | Market is closed                 | Expected — LTP is live only 9:15–15:30 IST                          |
| `Port 8000 already in use`      | Previous backend still running   | `pkill -f uvicorn`                                                  |
| `Port 5173 already in use`      | Previous Vite dev server running | `pkill -f vite`                                                     |
