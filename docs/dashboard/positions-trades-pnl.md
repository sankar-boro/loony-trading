# Positions, Trades and Daily P&L

Three pages show what the bot is holding and how it has done. All three read
files written by the bots — they need no database and no Upstox token, only a
bot that has run (or `python scripts/seed_dashboard_data.py` for sample data).

## Positions

`/positions`, `pages/Positions.tsx`, polling `GET /api/positions` every 10 s.
The endpoint returns `data/live_positions.json` as written by whichever bot
ran last: `scripts/paper_trade.py`, or `main.py` in paper or live mode.

### Exposure bar

Shows **Deployed** (share of capital in positions, `(capital − cash) ÷ capital`),
**Cash** and total **Unrealised** P&L, with a bar from 0 to 100 % deployed and
the count of open positions. The time in the header is the file's `saved_at`.

### Open positions

One row per position:

| Field | Meaning |
|---|---|
| Symbol, ▲ LONG / ▼ SHORT | Direction (`direction` 1 or −1) |
| Strategy badge | Strategy that opened the position |
| Entry time | When it was opened |
| Qty, Entry, CMP | Size, entry price, current market price |
| Stop, Target | Current stop-loss (moves up with the trailing stop) and take-profit |
| SL→TP bar | How far the current price sits between stop and target |
| P&L | Unrealised P&L in ₹ and % of position value |

When the file does not exist the page says **Bot not running** and suggests
`python scripts/paper_trade.py`.

### Signal log

The latest 100 events from the paper trader's `signal_log` — **BUY**, **SELL**
(entries) and **CLOSE** (exits, with P&L) — newest first. `main.py` does not
keep a signal log, so this panel stays empty while it is the active bot; its
events are in `logs/trading.log` and `logs/trades.jsonl` instead.

## Trades

`/trades`, `pages/Trades.tsx`. Toggle between **paper** and **live**:

| Source | File | Written by |
|---|---|---|
| paper | `logs/paper_trades.jsonl` | `scripts/paper_trade.py` on every close |
| live | `logs/trades.jsonl` | `main.py` (`TradeLogger`) on every close, paper or live mode |

`GET /api/trades?source=paper|live` (every 30 s) returns closed trades (records
with a `pnl` field) and statistics:

| Stat | Definition |
|---|---|
| Total, Wins, Losses | Counts; a trade with P&L ≤ 0 counts as a loss |
| Win Rate | Wins ÷ total |
| Total P&L | Sum of P&L |
| Profit Factor | Gross profit ÷ gross loss (as a positive number) |
| Avg Win, Avg Loss | Mean P&L of winners / losers |
| Expectancy | `win% × avg win + loss% × avg loss` — average P&L per trade |

Below the stats are two charts — **P&L by Strategy** (total per strategy,
sorted) and **P&L Distribution** (histogram of trade P&L) — and the trade
table: date, symbol, side, strategy, entry, exit, quantity, P&L and the exit
reason:

| Reason | Bot | Meaning |
|---|---|---|
| `stop_loss` | both | Price hit the stop — including a stop raised by the trailing stop |
| `take_profit` | both | Price hit the target |
| `signal_close`, `reverse_signal` | paper trader | A new signal closed the position |
| `signal_reversal` | `main.py` | An opposite signal closed the position |
| `mis_squareoff_3:14pm` / `mis_squareoff` | paper trader / `main.py` | Intraday positions closed at 15:14 IST |
| `reconcile_missing_at_broker` | `main.py` live | Removed because Upstox did not hold it (see [Position Safety](../engine/position-safety.md)) |

### Execution quality

The **Execution quality** button switches the Trades page to how well orders
were filled, for the chosen paper or live source over 7, 30 or 90 days:
- the fill rate, slippage against the price the bot decided at (basis
  points, + = cost), the slippage cost in rupees, and the order outcomes;
- tables by entry/exit, order type, chases (limit orders), hour and
  strategy.

The data comes from `logs/executions.jsonl`; see
[Execution quality](../engine/execution.md#execution-quality).

## Daily P&L

`/daily`, `pages/DailyPnL.tsx`, reading `GET /api/daily` — one record per
trading day from `data/daily_pnl.jsonl`, appended by the paper trader's
end-of-day report at 15:35 IST (or when it stops).

| KPI | Definition |
|---|---|
| Total Realised | Sum of daily realised P&L |
| Avg Daily | Mean daily realised P&L |
| Sharpe (ann.) | `mean ÷ stdev × √252` of daily P&L as a fraction of `portfolio.initial_capital` |
| Win Rate | Winning trades ÷ all trades across all days |
| Trading Days | Number of records |
| Best Day, Worst Day | Highest and lowest daily realised P&L |

Charts: **Cumulative P&L** (running total) and **Daily Realised** (green/red
bars). The table lists each day's realised P&L, trades, wins/losses, win %,
maximum drawdown % (from the sequence of that day's closed trades) and the
symbol of the day's best trade.

The command-line equivalents are `python scripts/daily_report.py` and
`python scripts/trade_journal.py` — see [Command-Line Tools](../operations/cli.md).
