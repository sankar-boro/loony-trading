# Paper Trading

`scripts/paper_trade.py` is a self-contained paper-trading session: real
Upstox prices, the real strategy engine, a virtual portfolio, a live terminal
dashboard, and the files the web dashboard reads. **It never places an
order.** (The other paper mode, `python main.py --mode paper`, runs the full
live bot with simulated fills — see
[Architecture of the Bot](../engine/architecture.md).)

## Running it

```bash
python scripts/paper_trade.py                         # 15 default large caps
./loony.sh paper --symbols RELIANCE,TCS,HDFCBANK --tick 30
```

| Option | Default | Meaning |
|---|---|---|
| `--symbols` | 15 large caps | Comma-separated universe symbols |
| `--capital` | 5,00,000 | Starting virtual capital (₹) |
| `--tick` | 60 | Seconds between price polls |
| `--signal-every` | 5 | Generate signals every N ticks |
| `--max-positions` | 5 | Maximum open positions |
| `--risk-per-trade` | 0.01 | Fraction of cash risked per trade (overrides `risk.max_risk_per_trade`) |
| `--timeframe` | `1d` | Bars for strategies: `1d` (2 years), or intraday such as `1h` |
| `--log-file` | — | Also append every event to this JSONL file |
| `--token` | — | Explicit access token |

It reads `config/settings.yaml` for the enabled strategies and weights.

## What happens each tick

1. **Outside market hours** it waits — sleeping until two minutes before the
   next open (weekends and NSE holidays skipped).
2. **Fetch prices** for all symbols in one LTP request.
3. **15:14 IST** (once a day): close every open position at the last price,
   reason `mis_squareoff_3:14pm`. The paper trader treats all its trades as
   intraday.
4. **Stops and targets**: mark positions to market, move trailing stops
   (2 %), close any position whose stop or target was hit.
5. **Intraday refresh**: on an intraday timeframe, fetch the newest candles
   once per bar period and merge them in.
6. **Every `--signal-every` ticks**: patch the latest bar's close with the
   live price, run `generate_signals()` → `best_signal()` per symbol, and act:
   - same direction as an open position → ignore;
   - opposite direction → close the position (`reverse_signal`) and open the
     new one;
   - new position if fewer than `--max-positions` are open and there is cash.
7. **15:35 IST** (once): end-of-day report.
8. Redraw the terminal dashboard, save the state file, append an equity
   snapshot, sleep until the next tick.

Ctrl+C saves the state, writes the end-of-day report if it has not run yet,
and prints a summary.

## Position sizing and costs

- Risk `--risk-per-trade` of current **cash** over the distance to the stop,
  capped at 25 % of cash, whole shares.
- Missing stops/targets default to 2 % / 4 % from entry.
- A flat **0.1 % commission per side** is charged — simpler than the
  executor's itemised NSE charges, and more conservative for intraday trades.

## Files it writes

| File | Content | Read by |
|---|---|---|
| `data/live_positions.json` | Cash, open positions, closed trades, last 200 signal-log events, `saved_at` | Positions page, Portfolio Risk, Bot status light; restore on restart |
| `data/equity_curve.jsonl` | One line per tick: equity, cash, realised, unrealised, open positions | Home equity curve |
| `logs/paper_trades.jsonl` | One line per closed trade | Trades (paper), Strategies, trade journal |
| `data/daily_pnl.jsonl` | One line per day: realised P&L, trades, wins, losses, win rate, max drawdown %, top symbol | Daily P&L page, daily report |

Formats: [Logs and Data Files](logs-and-data-files.md).

## Restarting

On start it restores the previous session from `data/live_positions.json` when
the snapshot is less than an hour old and was made with the same
`--capital` — positions, cash, closed trades and the signal log continue where
they left off. Older snapshots, and files written by `main.py`, are ignored.

## Notifications

With `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set, it sends a start message,
every entry and exit, and the end-of-day summary. See
[Notifications](notifications.md).

## Seeding sample data instead

`python scripts/seed_dashboard_data.py` backtests five stocks over 180 days and
writes the same four files, so the dashboard pages can be explored without
waiting for a live session.
