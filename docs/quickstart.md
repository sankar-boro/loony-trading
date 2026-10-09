# Quickstart Guide

Get the bot running in paper mode in under 10 minutes.

---

## 1. Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| pip | latest |
| Upstox account | with API access enabled |
| (Optional) Telegram bot | for trade alerts |

---

## 2. Install

```bash
git clone <your-repo-url>
cd loony-trading
pip install -r requirements.txt
```

For GPU-accelerated deep learning (optional):
```bash
pip install tensorflow-gpu   # or torch with CUDA
```

---

## 3. Configure Credentials

```bash
cp .env.example .env
```

Edit `.env` — minimum required for paper trading:

```env
# Upstox — get from https://upstox.com/developer/
UPSTOX_API_KEY=your_api_key
UPSTOX_API_SECRET=your_api_secret
UPSTOX_REDIRECT_URI=http://localhost:3561/callback

# Optional: paste a pre-obtained access token to skip browser auth on each start
UPSTOX_ACCESS_TOKEN=
```

For live trade alerts, add:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

**NEVER commit `.env` to git.** It is in `.gitignore`.

---

## 4. First-Time Upstox Authentication

On first run, the bot opens a browser for Upstox OAuth:

```bash
python main.py --mode auth
```

1. Browser opens → log in to Upstox → approve API access
2. You are redirected to `http://localhost:3561/callback`
3. The bot captures the token and saves it to `data/upstox_token.json`
4. Subsequent runs reuse this token automatically (valid ~24 hours)

To get an Analytics token (read-only, for market data without trading permissions):
- Log in to Upstox → Developer Console → generate an Analytics token
- Paste it into `UPSTOX_ACCESS_TOKEN=` in `.env`

---

## 5. Run Modes

### Paper Trading (no real money)
```bash
python main.py --mode paper
```
Simulates order execution with realistic slippage. All trades are logged but no
real orders are placed.

### Backtesting
```bash
python main.py --mode backtest
```
Runs all enabled strategies against historical data. Results appear in
`logs/backtest_<date>.log` and on the dashboard.

### ML Model Training
```bash
python main.py --mode train
```
Pulls 180 days of historical data, builds features, trains XGBoost + LightGBM +
LSTM models, saves to `models/`.

### Live Trading
```bash
python main.py --mode live
```
**Requires a fully authenticated Upstox session with trading permissions.**
Starts placing real orders. Make sure you've tested in paper mode first.

---

## 6. Launch the Dashboard

```bash
bash dashboard/start.sh
```

Open http://localhost:5163 in your browser (FastAPI backend runs on :8000).

Pages:
- **Dashboard** — real-time prices, open positions, latest signals
- **Chart** — TradingView-style candlestick chart per symbol
- **Positions** — open positions
- **Trades** — trade log
- **Strategies** — per-strategy trade stats and signal attribution
- **Backtest** — historical performance metrics
- **Daily PnL** — equity curve, drawdown chart
- **News** — classified news events
- **Signals** — composite signal scores per stock
- **Copilot** — AI Q&A over signals and news
- **Watchlists** / **Alerts** — your lists and rule-based alerts
- **Portfolio Risk** — exposure and correlation
- **Intraday Lab** — intraday scans and alert evaluation
- **Docs** — these markdown docs, rendered

---

## 7. Read the Logs

All logs go to `logs/` as structured JSON:

```bash
# Watch live trading log
tail -f logs/trading.log | python -m json.tool

# Quick grep for errors
grep '"level":"ERROR"' logs/trading.log

# Trade log (every entry/exit)
tail -f logs/trades.jsonl
```

Log fields:
```json
{
  "timestamp": "2026-05-27T09:32:15.123",
  "level": "INFO",
  "logger": "meta_engine",
  "message": "Signal: BUY RELIANCE strength=0.82 strategy=ema_crossover"
}
```

---

## 8. Run Tests

```bash
# All offline tests (~483 tests, ~30 seconds)
pytest tests/ -v --ignore=tests/test_live_upstox.py

# Specific module
pytest tests/test_strategies.py -v
pytest tests/test_p6_p14.py -v

# Live Upstox API tests (requires access token)
export UPSTOX_ACCESS_TOKEN=your_token
pytest tests/test_live_upstox.py -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

---

## 9. Docker (Optional)

```bash
cp .env.example .env   # fill credentials
docker compose up -d   # starts Postgres, Redis, bot + dashboard on port 8000
docker compose logs -f # watch logs
```

---

## 10. Typical First Session Checklist

- [ ] `pip install -r requirements.txt` — dependencies installed
- [ ] `.env` configured with API keys — credentials set
- [ ] `python main.py --mode auth` — Upstox OAuth completed
- [ ] `python main.py --mode paper` — paper trading running
- [ ] `bash dashboard/start.sh` — dashboard open
- [ ] `pytest tests/ --ignore=tests/test_live_upstox.py` — all offline tests pass
- [ ] `tail -f logs/trading.log` — watching live logs
