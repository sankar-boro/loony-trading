# Logs and Data Files

The bots and scripts communicate through files in `data/`, `logs/` and
`models/` — all git-ignored, created on first use. This chapter lists every
file, who writes it, who reads it and its format.

> Paths are relative to the **working directory** for the logger
> (`logs/trading.log`) and a few caches; run commands from the repository root
> so everything lands in one place.

## logs/

| File | Written by | Format |
|---|---|---|
| `trading.log` | Every component (`utils/logger.get_logger`) | JSON lines (below) |
| `trades.jsonl` | `main.py` bot (`TradeLogger`) — orders and closes, paper and live mode | JSON lines |
| `paper_trades.jsonl` | `paper_trade.py` — one line per closed trade | JSON lines |
| `dashboard_backend.log`, `dashboard_frontend.log` | `dashboard/start.sh` | Plain text |
| `auto_login.log` | `auto_login.sh` via your cron entry | Plain text |

### trading.log

Each line is one JSON object, also printed to stdout:

```json
{"ts": "2026-10-09T04:02:15.441+00:00", "level": "INFO", "logger": "main",
 "msg": "MIS squareoff triggered at 3:14 PM IST — closing all intraday positions"}
```

Errors with a traceback add an `exc` field. Logger names identify the
component (`main`, `meta_engine`, `risk_manager`, `upstox.execution`,
`upstox.feed`, `scheduler.jobs`, `news.pipeline`, …). The level comes from
`system.log_level` for `main`, INFO elsewhere.

```bash
tail -f logs/trading.log | python -m json.tool --json-lines
grep '"level": "ERROR"' logs/trading.log
grep '"logger": "upstox.execution"' logs/trading.log
./loony.sh logs --errors          # tails the backend log, errors only
```

The file is never rotated; `health.py` warns when logs grow large.

### trades.jsonl

```json
{"ts": "…", "type": "order", "symbol": "INE002A01018", "side": "BUY", "quantity": 25,
 "price": 2801.5, "product": "CNC", "strategy": "loony-donchian_breakout"}
{"ts": "…", "type": "close", "symbol": "RELIANCE", "direction": 1, "entry_price": 2801.5,
 "exit_price": 2766.0, "size": 25, "pnl": -887.5, "reason": "stop_loss",
 "strategy": "donchian_breakout"}
```

### paper_trades.jsonl

```json
{"ts": "…", "type": "close", "symbol": "TCS", "direction": 1, "strategy": "zscore_reversion",
 "entry_price": 4012.0, "exit_price": 4093.0, "size": 12, "pnl": 972.0,
 "reason": "take_profit", "entry_time": "10:41:02", "exit_time": "14:05:44"}
```

The dashboard's Trades page and the trade journal count only lines with a
`pnl` field.

## data/

### Written by the bots

| File | Writer | Content |
|---|---|---|
| `live_positions.json` | `paper_trade.py` or `main.py` (whichever ran last) | Open positions and portfolio state; `saved_at` drives the **Bot** status light. Formats in [Paper Trading](paper-trading.md#files-it-writes) and [Position Safety](../engine/position-safety.md#crash-recovery) |
| `equity_curve.jsonl` | `paper_trade.py`, every tick | `{"ts", "equity", "cash", "realised", "unrealised", "open_pos"}` |
| `intraday_pnl.jsonl` | `main.py`, once a minute | `{"ts", "realised", "unrealised", "total", "open_positions"}` — the Intraday Desk's P&L curve |
| `live_bars/<YYYY-MM-DD>/<SYMBOL>.csv` | `main.py`, every finished 1-minute bar (`intraday.record_bars`) | `ts,open,high,low,close,volume`; read by `BarRecorder` and `backtest_runner.py --source recorded`. See [Recording live bars](../engine/intraday-controls.md#recording-live-bars) |
| `daily_pnl.jsonl` | `paper_trade.py`, end of day | `{"date", "realised", "unrealised", "trades", "wins", "losses", "win_rate", "max_drawdown_pct", "top_symbol"}` |

### Written by the dashboard

| File | Writer | Content |
|---|---|---|
| `bot_control.json` | Intraday Desk buttons (`POST /api/intraday/control`) | `{"paused", "flatten_id", "resume_id", "updated_at"}`, read by `main.py` on each tick. See [Operator controls](../engine/intraday-controls.md#operator-controls) |

### Tokens

| File | Content |
|---|---|
| `upstox_token.json` | Daily access token + `obtained_at` |
| `upstox_extended_token.json` | Long-lived read-only token |
| `upstox_sandbox_token.json` | Sandbox token |

These grant access to your account — keep `data/` private.

### Caches (safe to delete)

| Path | Content | Refreshed |
|---|---|---|
| `cache/upstox_<symbol>_<tf>.parquet` | Candles | after 1 h (intraday) / 12 h (daily) |
| `instruments/<SEGMENT>.json` | Upstox instrument master per segment | after 18 h |
| `instruments/NSE.csv`, `.xlsx` | Master downloaded by `fetch_instruments.sh` | manual |
| `corporate_actions.json` | Split/bonus factors from NSE | daily |
| `nse_holidays.json` | NSE trading holidays | every 30 days |
| `nse_cache/` | FII/DII, delivery, F&O ban, VIX history (parquet) | daily |
| `feature_cache/` | Cross-asset macro features | daily |

## models/

| File | Content |
|---|---|
| `ensemble.pkl` | The trained ML ensemble with its feature columns and evaluation report — present only after a training run that passed the gate |
| `xgboost.pkl`, `lightgbm.pkl` | The ensemble's members |
| `hmm/hmm_<SYMBOL>.pkl` | Fitted HMM regime models (none are fitted by default; test runs may leave `hmm_SYM1/SYM2/TEST` here) |

## Backing up

Worth keeping: `logs/trades.jsonl`, `logs/paper_trades.jsonl`,
`data/daily_pnl.jsonl`, `data/equity_curve.jsonl`, `models/`, your `.env` and
`config/settings.yaml` — plus a PostgreSQL dump for MarketPulse. Everything else
regenerates.
