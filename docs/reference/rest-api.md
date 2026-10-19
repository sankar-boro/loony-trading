# REST API Reference

The dashboard backend (`dashboard/backend/`, FastAPI) serves every endpoint
under `/api` on port 8000. An interactive explorer with request and response
schemas is at **http://localhost:8000/api/docs** (Swagger UI).

**Login.** With `DASHBOARD_PASSWORD` set, every endpoint except
`/api/health` and `/api/auth/*` needs a session: log in with
`POST /api/auth/login`, which sets an HttpOnly cookie and also returns the
token for scripts (`Authorization: Bearer <token>`). Without a password, the
API answers only this machine and returns 401 to everyone else. See
[Dashboard login](../operations/deployment.md#dashboard-login).

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | Body `{"password": "…"}` → `{ok, token, expires_in}` and a session cookie; 401 wrong password, 429 after 5 failures in 5 minutes, 400 if no password is configured |
| POST | `/api/auth/logout` | Clears the session cookie |
| GET | `/api/auth/status` | `{password_set, local, authenticated}` |

Conventions: JSON in and out; errors are `{"detail": "…"}` with an HTTP status
(400 bad input, 401 not logged in or missing/expired Upstox token, 404 unknown
resource, 500 server error). "Token" below means a valid Upstox daily token; endpoints marked
**DB** need PostgreSQL.

## System

| Method | Path | Description |
|---|---|---|
| GET | `/api/status` | `bot_running`, `market_open`, `mins_to_close`, `next_market_open`, `token_valid`, `token_age_h`, `demo_mode` |
| GET | `/api/health` | 200 `{"status": "healthy", "checks": {...}}` or 503 `"degraded"` — token, data files, strategy engine import, ML model |
| GET | `/api/config` | `weights`, `enabled`, `capital`, `all_strategies` from `settings.yaml` |
| GET | `/api/scheduler/status` | `running`, `next_runs` per job, `last_runs` (ok, detail, duration) |
| GET | `/api/telegram/test` | Checks Telegram settings and sends a test message |

## Portfolio files (written by the bots)

| Method | Path | Description |
|---|---|---|
| GET | `/api/positions` | `positions`, `signal_log`, `cash`, `initial_capital`, `saved_at` from `data/live_positions.json` |
| GET | `/api/equity` | Array of equity snapshots from `data/equity_curve.jsonl` |
| GET | `/api/trades?source=paper\|live` | `trades` (closed trades) and `stats` (total, wins, losses, win_rate, total_pnl, avg_win, avg_loss, expectancy, profit_factor) |
| GET | `/api/execution/quality?days=30&mode=paper\|live` | Fill rate and slippage vs the decision price from `logs/executions.jsonl`: `overall`, `outcomes`, `by_kind`, `by_order_type`, `by_strategy`, `by_hour`, `by_chases` |
| GET | `/api/daily` | `days` from `data/daily_pnl.jsonl` and `summary` (total_realised, avg_daily, best_day, worst_day, sharpe_ann, total_trades, overall_win_rate) |
| GET | `/api/intraday/desk` | Everything the [Intraday Desk](../dashboard/intraday-desk.md) shows: `session` (phase, entry window, minutes to last entry / squareoff / close), `bot` (running, mode, feed age, `feed_stale`, `exchange_stops`), `guard` (trade counts, caps, cooldowns, halt, pause), `control`, `pnl` (realised, unrealised, day, loss limit, `loss_used_pct`, profit lock), `positions`, today's `trades`, `by_strategy`, `curve` (minute P&L) and today's `events` (newest first) |
| POST | `/api/intraday/control` | Body `{"action": "pause" \| "resume" \| "flatten"}` → writes `data/bot_control.json`; returns `{ok, action, control}`. 400 for any other action |
| GET | `/api/portfolio/analytics` | For the open positions: `beta` (per stock, portfolio, hedge or `hedge_note`), `factors` (loadings, t-stats, R², alpha, sector exposure), `stress` (crisis scenarios). Fetches a year of daily bars |
| GET | `/api/portfolio/risk` | Capital, cash, market value, exposure, daily/unrealised P&L, max loss, `sector_exposure_pct`, `correlation` matrix, `warnings` |

## Market data (token)

| Method | Path | Description |
|---|---|---|
| GET | `/api/universe` | `sectors` (each with `stocks`: symbol, name, industry, market_cap, fno, nifty50), `total_stocks`, `watchlist` |
| GET | `/api/watchlist` | `{SYMBOL: {ltp, change, change_pct, volume}}` for the 30 default watchlist symbols |
| GET | `/api/market` | `{ltp, change_pct}` for NIFTY50, BANKNIFTY and NIFTYIT, from daily candles |
| GET | `/api/ltp?symbols=A,B` | `{SYMBOL: last price}` |
| GET | `/api/chart/{symbol}?interval=…&days=…` | `{symbol, interval, candles: [{time, open, high, low, close, volume}]}`; intervals `day`, `60minute`, `30minute`, `15minute`, `5minute`, `1minute`; days 1–730 (capped per interval) |
| GET | `/api/stream/prices` | Server-Sent Events: a `{watchlist, market, ts}` snapshot every 2 s (10 s without token) |
| GET | `/api/signals` | Live strategy scan of 10 liquid stocks — top 10 signals with confidence ≥ 0.4 (symbol, signal, strategy, confidence, price, stop_loss, take_profit). May send Telegram messages |

## Backtesting (token)

| Method | Path | Description |
|---|---|---|
| POST | `/api/backtest` | Submit a job → `{"job_id": "…"}` |
| POST | `/api/backtest/batch` | Same as above (kept for compatibility) |
| GET | `/api/backtest/{job_id}` | `{job_id, status: pending\|running\|done\|error, result, error}` |

Request body (all optional except a symbol):

```json
{
  "symbol": "RELIANCE",            "symbols": [],
  "strategy": "donchian_breakout", "strategies": [],
  "days": 365,                     "timeframe": "1d",
  "capital": 500000,               "product": "CNC",
  "risk": {"max_risk_per_trade": 0.005},
  "feature_engineer": true,
  "benchmark": false, "monte_carlo": false,
  "walk_forward": false, "walk_forward_splits": 5,
  "token": ""
}
```

`strategy` (one name) runs that strategy alone; `strategies` (a list) runs the
meta engine restricted to them. Timeframes: `1d`, `1h`, `30m`, `15m`. The
result has `symbols`, `results` (one per symbol: metrics, `equity_curve`,
`trades_pnl`, `trades`, optional `benchmark` and `monte_carlo`, or
`walk_forward` with `splits` and `final_split`) and `errors` for symbols that
failed.

## MarketPulse (DB)

### Signals

| Method | Path | Description |
|---|---|---|
| GET | `/api/signals/composite` | Query: `direction` (bullish/bearish/watch/no_signal), `symbol`, `timeframe` (default `1d`), `latest_only` (default true — one row per stock), `limit` (≤ 500). Rows: id, symbol, timeframe, timestamp, direction, score, confidence, `components` |
| GET | `/api/signals/composite/{id}` | One signal including `trade_setup` (entry_low/high, stop_loss, target_1/2, risk_reward) |
| GET | `/api/signals/performance?days=90` | Track record of past signals: `baseline`, `by_direction` (averages, hit rates, excess, setups), `by_score`, `components` (correlations); 7–365 days |
| POST | `/api/signals/intraday-scan` | Body `{symbols: [], limit: 5, lookback_days: 5, timeframe: "30m"}` → the `run_signal_engine` summary. Synchronous |
| GET | `/api/stocks/{symbol}/why` | Explanation: signal, drivers, recent_news, historical_analogue, conclusion |
| GET | `/api/historical-analogues?event_type=…&direction=…&symbol=…` | Per-horizon sample counts, win rates and median returns |

### News

| Method | Path | Description |
|---|---|---|
| GET | `/api/news?event_type=…&symbol=…&limit=50` | Classified news events (≤ 200), newest first |
| GET | `/api/news/event-types` | The 30 event-type slugs |
| POST | `/api/news/ingest?limit=20` | Run one ingestion pass → `{fetched, ingested, skipped_duplicate, events_created}` |

### Copilot

| Method | Path | Description |
|---|---|---|
| POST | `/api/copilot/query` | Body `{"question": "…"}` → `{answer, confidence, evidence, insufficient_evidence}` |

### Watchlists

| Method | Path | Description |
|---|---|---|
| GET | `/api/watchlists` | `[{id, name, created_at, symbols}]` |
| POST | `/api/watchlists` | Body `{"name": "…"}` |
| DELETE | `/api/watchlists/{id}` | Delete a list |
| POST | `/api/watchlists/{id}/items` | Body `{"symbol": "TCS"}` (idempotent) |
| DELETE | `/api/watchlists/{id}/items/{symbol}` | Remove a symbol |

### Alerts

| Method | Path | Description |
|---|---|---|
| GET | `/api/alerts` | All alerts, newest first |
| POST | `/api/alerts` | Body `{"name", "condition": {"score__gte": 75, …}, "symbol": null}` — 400 on an invalid condition |
| PATCH | `/api/alerts/{id}?is_active=true\|false` | Pause or resume |
| DELETE | `/api/alerts/{id}` | Delete |
| GET | `/api/alerts/{id}/triggers?limit=50` | Trigger history: symbol, signal_id, matched_values, created_at |
| POST | `/api/alerts/evaluate?timeframe=1d` | Evaluate all active alerts now → `{alerts_checked, timeframe, triggers}`; notifies Telegram |

## Documentation

| Method | Path | Description |
|---|---|---|
| GET | `/api/doc-files` | The handbook's table of contents: parts → chapters (path, title, number) → sections (id, title) |
| GET | `/api/doc-files/search?q=…&limit=40` | Full-text search hits with chapter, section and snippet |
| GET | `/api/doc-files/{path}` | One chapter's markdown (only `.md` files under `docs/`) |

## Frontend routes

In production the backend also serves the React app: `/assets/*` from
`dashboard/frontend/dist/assets`, and any other non-API path returns
`index.html` so client-side routes (`/signals`, `/docs/...`) load directly.
