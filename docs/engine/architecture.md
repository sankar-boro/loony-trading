# Architecture of the Bot

`main.py` is the entry point for the trading bot (`UpstoxTradingBot`) and for
the backtest, training and login modes. This chapter follows the bot from
startup through every tick to shutdown.

## Entry points

```bash
python main.py --mode paper      # default (system.mode in settings.yaml)
python main.py --mode live
python main.py --mode backtest [--market india|crypto]
python main.py --mode train
python main.py --mode auth
```

| Mode | Runs |
|---|---|
| `paper`, `live` | `UpstoxTradingBot(cfg, mode).start()`; Ctrl+C calls `stop()` |
| `backtest` | `run_backtest()` — every symbol in `assets.india_equity` + `india_indices` on `timeframes.primary` with the enabled strategies, printing one summary line each ([Backtesting](backtesting.md)) |
| `train` | `run_training()` — the gated ML training ([Machine Learning](machine-learning.md)) |
| `auth` | `run_auth()` — browser OAuth on `exchanges.upstox.auth_port` ([Connecting to Upstox](../getting-started/upstox-access.md)) |

## Components

`UpstoxTradingBot.__init__` wires these together:

```
UpstoxAuth ─► InstrumentRegistry ─► UpstoxDataEngine   (history)
                     │
                     └──────────► UpstoxFeed            (WebSocket ticks) ──► _on_tick
RiskManager ◄── UpstoxExecutor (orders, paper fills)  ── on_fill ──► TradeLogger
PortfolioManager   MetaStrategyEngine   LiveBarAggregator   Notifier
```

| Component | Role |
|---|---|
| `UpstoxAuth` | Loads the daily token (`data/upstox_token.json`, else `UPSTOX_ACCESS_TOKEN`) |
| `InstrumentRegistry` | Symbol ↔ instrument key, lot and tick sizes (NSE equity, F&O, indices) |
| `UpstoxDataEngine` | Historical candles with caching and split/bonus adjustment |
| `UpstoxFeed` | Real-time ticks in `full` mode |
| `RiskManager` | Validation, sizing, stops, open positions |
| `PortfolioManager` | Price history for the correlation guard, trade log, metrics |
| `UpstoxExecutor` | Orders (live) or simulated fills (paper) |
| `MetaStrategyEngine` | All enabled strategies (and the ML model, if one is saved) |
| `LiveBarAggregator` | One-minute bars from ticks |
| `Notifier`, `TradeLogger` | Telegram/e-mail messages; `logs/trades.jsonl` |

Symbols traded: `assets.india_equity` plus `assets.india_indices`.

## Startup

1. **Token check** — computes the real 03:30 IST expiry. Live mode stops if the
   token is expired or missing; paper warns. Both warn within three hours of
   expiry.
2. **Restore positions** from `data/live_positions.json` if the file was
   written by this bot in the same mode ([Position Safety](position-safety.md#crash-recovery)).
3. **ML check** — reports whether `models/ensemble.pkl` (or the XGBoost +
   LightGBM pair) exists.
4. **Load history** — `data.lookback_days` (365) of `timeframes.primary` bars for
   every symbol, plus 60 days of `timeframes.intraday` bars for every equity
   symbol (a short pause between requests respects rate limits). The intraday
   frames are kept as the "base" onto which live bars are spliced.
5. **Load models** — saved models only; the bot never trains.
6. **Market closed?** Paper mode runs one pass of the strategies over the
   cached daily data (`_run_paper_simulation`) and exits. Live mode carries on
   and waits for ticks.
7. **Live only** — reconcile with Upstox, then start the periodic
   reconciliation task.
8. **Start the feed** for all symbols; this call runs until shutdown.

## The tick loop

Every tick event goes through `_on_tick` → `_process_tick`, then
`_save_state()` (which writes the state file if anything changed or 5 s have
passed):

1. **Sanity check** the price; drop it if corrupt
   ([The Live Feed](live-feed.md#tick-sanity-check)). Record it as the last
   price and the time of the last tick (for the feed heartbeat).
2. **New trading day?** Reset the risk manager's daily P&L and trade count,
   and the intraday guard's caps, cooldowns and halt.
3. **Operator commands** from `data/bot_control.json`: pause, resume,
   flatten ([Intraday Session Controls](intraday-controls.md#operator-controls)).
4. **15:14 IST?** Run the once-a-day MIS squareoff
   ([Position Safety](position-safety.md#intraday-mis-squareoff)).
5. Record the price in the portfolio manager.
6. **Stops and targets** — `RiskManager.update_all()` moves trailing stops and
   returns positions to close; each is closed through the executor, logged,
   recorded and announced. With exchange-held stops, the broker's stop order
   is moved to the new trailing level.
7. **Day limits** — kill switch and profit lock on realised + unrealised day
   P&L; append the minute P&L point.
8. **Live bars** — feed the 1-minute aggregator and record each finished bar
   to `data/live_bars/`.
9. **Has a bar closed?** For symbols with an intraday base, continue only when
   a full `timeframes.intraday` bar has completed, then rebuild the frame
   (history + live bars). Symbols without an intraday base use the daily frame.
10. Need at least 60 bars.
11. **No new intraday entries after 15:14** when trading MIS.
12. **Score** — `meta_engine.generate_signals()` → `best_signal()` (confidence
    × weight); continue only for BUY/SELL.
13. **Existing position?** Same direction → ignore. Opposite
    direction → close it (`signal_reversal`) and stay flat.
14. **Session rules** — pause, halt, entry window, trade caps, cooldown
    ([Intraday Session Controls](intraday-controls.md#session-rules)); a
    blocked signal is logged as a `block` event.
15. **Correlation guard** — skip if the symbol's recent returns correlate above
    0.7 with an open position.
16. **Execute** — `executor.execute_signal()` (validation, sizing, order, fill
    handling). On a completed fill, count the entry, place the exchange stop
    if enabled, and send a notification.

## Background tasks

| Task | When |
|---|---|
| Reconciliation with Upstox | Live mode: startup and every `execution.reconcile_interval_sec` (300 s); then places any missing exchange-held stops |
| Feed heartbeat | Every 30 s in market hours; alerts after `intraday.heartbeat_minutes` without a tick |
| Feed reconnection | On any WebSocket error: 2 s, doubling to 60 s |

## Shutdown

Ctrl+C (KeyboardInterrupt) runs `stop()`: cancel the reconciliation task, close
the feed and write the state file one final time. Open positions remain open —
at the broker in live mode, and in the state file for the next start.

## Logging and notifications

- All components log JSON lines to stdout and `logs/trading.log`
  ([Logs and Data Files](../operations/logs-and-data-files.md)).
- Fills and closes are appended to `logs/trades.jsonl` (the dashboard's
  **live** trades).
- `Notifier` sends trade entries, closes, reconciliation alerts and squareoffs
  to Telegram/e-mail when configured ([Notifications](../operations/notifications.md)).

## Running it continuously

The bot is a single long-running process. A typical day:

```
08:45  cron: scripts/auto_login.sh renews the token (if expired)
09:00  systemd/cron starts: python main.py --mode live
09:15  ticks start; positions restored and reconciled
15:14  MIS squareoff (if trading MIS)
15:30  market closes; the bot keeps running, idle, until stopped
```

See [Deployment](../operations/deployment.md) for running it under systemd or
Docker.

## The crypto add-on

`CryptoBotAddon` in `main.py` can trade Binance pairs (`assets.crypto`) with
the same risk manager and strategies via `MarketDataEngine` (ccxt). It is not
started by any mode at present.
