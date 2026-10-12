# Troubleshooting

Symptoms, likely causes and fixes, grouped by area. When in doubt, start with
`./loony.sh health` and `logs/trading.log`.

## Tokens and Upstox

| Symptom | Cause | Fix |
|---|---|---|
| Amber **DEMO DATA** banner; red **Token missing** | No valid daily token | `python scripts/upstox_login.py` |
| Token worked yesterday, fails this morning | Daily tokens expire at 03:30 IST | Log in again; schedule `scripts/auto_login.sh` |
| `PermissionError: Upstox token invalid or expired` | Same, or a revoked token | Same |
| `401 Invalid token used to access API` on prices but candles still load | The token is invalid; historical candles do not always check it | Log in again |
| OAuth page redirects to an error | `UPSTOX_REDIRECT_URI` differs from the app's registered redirect URL | Make them identical, including `http://` and the port |
| `--token-request` fails with `UDAPI1123` | Notifier URL not configured in the Upstox app | Set it to `http://localhost:3561/callback` |
| `HTTP 400` for 5- or 15-minute candles | Not available on your account | Use `30m` or `1h` (the defaults) |
| A stock returns no data at all | Stale ISIN after a split/bonus/rename | Download the master (`scripts/fetch_instruments.sh`), run `pytest tests/test_instrument_isins.py`, update `config/instruments.py` |
| `Could not download NSE_EQ instruments` | Master download failed | Universe symbols still resolve (seeded from `config/instruments.py`); retry later for F&O lot sizes |

## Dashboard

| Symptom | Cause | Fix |
|---|---|---|
| Page loads but every panel is empty | Backend not running | `./loony.sh status`; `./loony.sh start` |
| `Port 8000 already in use` | An old backend is running | `bash dashboard/stop.sh` (or `--force`) |
| Vite picked another port | 5163 in use | Use the port printed by `start.sh` |
| Positions/Trades/Daily P&L empty | No bot has run | Run `scripts/paper_trade.py`, or `scripts/seed_dashboard_data.py` for samples |
| **Bot** light stopped while the bot runs | No state save in the last 5 minutes — e.g. `main.py` outside market hours (no ticks) | Expected outside hours |
| News / Signals / Alerts error or empty | Database not reachable or not migrated | `docker compose up -d db`, `alembic upgrade head`, `scripts/backfill_stocks.py` |
| Signals page empty | Nothing scored yet | `python scripts/run_signal_engine.py` or enable the scheduler |
| Chart empty with a 401 | No token (the chart has no demo fallback) | Log in |
| Strategy Lab: "Token missing or expired" | Backtests download candles live | Log in |
| Home "change %" stuck near 0.00 % | Known limitation of the price stream | See [Project Status](../appendix/status.md) |
| Repeated Telegram messages from the Home page | The signal feed alerts on every poll | Close the Home page or unset Telegram for the backend |

## Strategies and signals

| Symptom | Cause | Fix |
|---|---|---|
| A strategy never fires | Not in `strategies.enabled`; wrong regime; or it needs inputs not supplied (`mtf_trend`, `order_book_imbalance`, pair trading) | [The Strategy Framework](../engine/strategy-framework.md) |
| `vwap_reversion` / `anchored_vwap` silent on daily data | They only trade intraday bars | Expected |
| `gift_nifty_gap` never fires | No GIFT Nifty data source | Known limitation |
| An unknown name in `enabled` | Typo — unknown names are ignored silently | Compare with `GET /api/config` → `all_strategies` |
| `FeatureBuilder` returns no rows | Fewer than ~200 bars (EMA-200) | Fetch more history (`--days 365`+) |
| ML strategy never fires | No trained model, or not enabled | `python scripts/train_ml.py --enable` (only enables a model that passes) |

## Trading bot

| Symptom | Cause | Fix |
|---|---|---|
| Live mode exits immediately | Token expired/missing | Log in |
| Paper mode exits right after loading | Market closed: it runs one pass and stops | Expected; run during market hours |
| "Reconciliation: … will correct if still different" | The broker shows less than the bot (often a fill still in progress) | Wait for the next check; if confirmed, the bot shrinks its position and alerts |
| "Upstox has a position the bot is not tracking" | A manual trade, or an order that timed out but filled | Close or manage it yourself in Upstox |
| "Order placement failed (not retried …)" | Network/API error on placing | Check the Upstox order book; reconciliation will flag a position if it went through |
| "dropped suspicious tick" | A price jumped over 20 % | Usually bad data; three consistent ticks re-base it |
| No entries in the afternoon | MIS product after 15:14 | Expected |
| Restored positions you closed by hand | The state file still lists them | Live: reconciliation removes them; paper: delete `data/live_positions.json` before starting |

## Scheduler

| Symptom | Cause | Fix |
|---|---|---|
| Jobs never run | `scheduler.enabled: false` (default) | Enable and restart the backend |
| Jobs run twice | More than one backend worker/process | Run a single uvicorn worker |
| Signal/alert jobs skip | Market closed (`market_hours_only`) | Expected |
| NewsAPI stops returning articles | Free tier quota (100/day) used up | Raise `news_interval_seconds` |

## Tests

| Symptom | Fix |
|---|---|
| Live tests skipped | Set `UPSTOX_ACCESS_TOKEN` to run `tests/test_live_upstox.py` |
| `test_instrument_isins` skipped | Download the master with `scripts/fetch_instruments.sh` |
| Unsure whether tests need Postgres | They do not — database tests use in-memory SQLite |
