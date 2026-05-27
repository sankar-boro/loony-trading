# P3 — Operational (Flying Blind)

These gaps mean the bot is running but you have no visibility into what it is doing,
how it is performing, or when something goes wrong.

---

## P3-1 · Telegram Alerts Not Wired Into Integration Scripts

**Status:** ❌ Not wired  
**Risk:** Signals fire, positions open and close, stop-losses are hit — you know nothing until you manually check the terminal. If the bot is running headless on a server, you have zero awareness.

### Problem

`utils/telegram_alerts.py` is complete and well-designed:
- `TelegramAlerter.trade_alert()` — trade entry/exit notification
- `TelegramAlerter.risk_alert()` — drawdown, circuit, strategy disabled
- `TelegramAlerter.daily_summary()` — end-of-day P&L report

But it is **never instantiated** in:
- `scripts/paper_trade.py`
- `scripts/live_signals.py`
- `main.py` (partially wired — needs verification)

### Setup required first

```bash
# 1. Create a Telegram bot via @BotFather → copy token
# 2. Send any message to your bot
# 3. Get your chat_id:
curl "https://api.telegram.org/bot{YOUR_TOKEN}/getUpdates" | python -m json.tool

# 4. Add to .env:
TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxx-yyyyyyy
TELEGRAM_CHAT_ID=123456789
```

Verify it works:
```bash
python -c "
from utils.telegram_alerts import TelegramAlerter
a = TelegramAlerter()
a.send('Test from loony-trading 🤖')
print('sent:', a.status_check())
"
```

### What needs to be built

**`scripts/paper_trade.py`** — add at the top of `main()`:
```python
from utils.telegram_alerts import TelegramAlerter
alerter = TelegramAlerter()   # reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from env

if alerter.enabled:
    alerter.send(
        f"📊 Paper trade session started\n"
        f"Capital: ₹{args.capital:,.0f} | Symbols: {', '.join(syms)}"
    )
```

On each trade (in `PaperPortfolio.on_signal()`):
```python
alerter.trade_alert(
    strategy=signal.strategy,
    symbol=signal.symbol,
    direction="BUY" if direction == 1 else "SELL",
    qty=int(size),
    price=price,
)
```

On stop-loss / take-profit close (in `PaperPortfolio._close_position()`):
```python
alerter.trade_alert(
    strategy=pos.strategy,
    symbol=symbol,
    direction="CLOSE",
    qty=int(pos.size),
    price=exit_price,
    pnl=pnl,
)
```

On session end (in `KeyboardInterrupt` handler):
```python
alerter.daily_summary(
    capital=portfolio.initial_capital,
    daily_pnl=portfolio.realised_pnl,
    trade_count=len(portfolio.closed_trades),
    win_rate=portfolio.win_rate / 100,
    drawdown_pct=0.0,   # compute from equity curve
)
```

**`scripts/live_signals.py`** — on each new BUY/SELL signal found:
```python
if best and best.signal_type in (SignalType.BUY, SignalType.SELL):
    alerter.send(
        f"🔔 Signal: {sym}\n"
        f"{best.signal_type.value.upper()} @ ₹{best.price:,.2f}\n"
        f"Strategy: {best.strategy} | Conf: {best.confidence:.0%}\n"
        f"SL: ₹{best.stop_loss:,.2f} | TP: ₹{best.take_profit:,.2f}"
    )
```

### Files to change
- Edit `scripts/paper_trade.py` → instantiate `TelegramAlerter`, wire into all trade events
- Edit `scripts/live_signals.py` → send alert on each new signal found
- Edit `main.py` → verify `TelegramAlerter` is instantiated in `UpstoxTradingBot`
- Edit `config/settings.yaml` → add `notifications.telegram.enabled: true`

### Acceptance criteria
- [ ] Running `paper_trade.py` sends a Telegram message on session start
- [ ] Every BUY/SELL/CLOSE generates a Telegram trade alert
- [ ] End of session (Ctrl+C) sends the daily summary
- [ ] If `TELEGRAM_BOT_TOKEN` is not set, the alerter is silently disabled (no crash)
- [ ] `python scripts/check_token.py` can optionally test Telegram connectivity

---

## P3-2 · Daily P&L Report

**Status:** ❌ Missing  
**Risk:** No way to know how the bot performed today without manually parsing logs. Over weeks, you have no aggregate performance data.

### Problem

The bot generates trades and P&L throughout the day, but there is no:
- End-of-day summary generated at 3:35 PM IST
- Running daily P&L file updated throughout the session
- Historical daily P&L time series

### What needs to be built

**`data/daily_pnl.jsonl`** — append one record per trading day:
```json
{"date": "2025-05-27", "realised": 2840.50, "unrealised": -120.0, "trades": 7, "wins": 5, "losses": 2, "win_rate": 71.4, "max_drawdown_pct": 1.2, "top_symbol": "RELIANCE"}
{"date": "2025-05-28", "realised": -540.0, "unrealised": 0.0, "trades": 4, "wins": 1, "losses": 3, "win_rate": 25.0, "max_drawdown_pct": 3.1, "top_symbol": "TCS"}
```

**End-of-day trigger** — add to `paper_trade.py` and `main.py`:
```python
from data_engine.upstox.market_hours import now_ist
from datetime import time as dt_time

def _eod_report(portfolio: PaperPortfolio, alerter: TelegramAlerter):
    """Generate end-of-day report at 3:35 PM IST."""
    record = {
        "date": date.today().isoformat(),
        "realised": portfolio.realised_pnl,
        "unrealised": portfolio.unrealised_pnl,
        "trades": len(portfolio.closed_trades),
        "wins": sum(1 for t in portfolio.closed_trades if t.pnl > 0),
        "losses": sum(1 for t in portfolio.closed_trades if t.pnl <= 0),
        "win_rate": portfolio.win_rate,
    }
    
    # Append to daily log
    log_path = ROOT / "data" / "daily_pnl.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")
    
    # Send Telegram summary
    alerter.daily_summary(
        capital=portfolio.initial_capital,
        daily_pnl=record["realised"],
        trade_count=record["trades"],
        win_rate=record["win_rate"] / 100,
        drawdown_pct=0.0,
    )
```

In the tick loop, trigger once at 3:35 PM:
```python
ist_now = now_ist().time()
if ist_now >= dt_time(15, 35) and not _eod_done:
    _eod_report(portfolio, alerter)
    _eod_done = True
```

**`scripts/daily_report.py`** — standalone script to print performance:
```bash
python scripts/daily_report.py              # today
python scripts/daily_report.py --days 30    # last 30 days
python scripts/daily_report.py --csv        # export to CSV
```

### Files to change
- Edit `scripts/paper_trade.py` → add `_eod_report()` trigger at 3:35 PM
- Edit `main.py` → same EOD report in live mode
- Create `scripts/daily_report.py` → reads `data/daily_pnl.jsonl`, prints stats
- Edit `utils/telegram_alerts.py` → verify `daily_summary()` format is correct

### Acceptance criteria
- [ ] `data/daily_pnl.jsonl` contains one record per day after each session
- [ ] Running `daily_report.py --days 30` shows 30-day P&L, Sharpe, win rate
- [ ] Telegram daily summary fires at 3:35 PM IST
- [ ] The report correctly shows ₹0 on days with no trades

---

## P3-3 · Trade Journal with Query Tool

**Status:** ⚠️ Partial  
**Risk:** `trade_logger.py` exists and writes to `logs/trades.jsonl`, but there is no query tool. You cannot answer "which strategy made the most money this week?" or "what is my average holding time per strategy?"

### Problem

`utils/trade_logger.py` logs all trades in structured JSON format.
The data is there, but there is no interface to query it.
Performance attribution requires being able to group by strategy, symbol, date range, direction.

### What needs to be built

**`scripts/trade_journal.py`** — query the trade log:

```
Usage:
  python scripts/trade_journal.py                     # today's trades
  python scripts/trade_journal.py --days 7            # last 7 days
  python scripts/trade_journal.py --strategy ema_crossover
  python scripts/trade_journal.py --symbol RELIANCE
  python scripts/trade_journal.py --winners           # only profitable trades
  python scripts/trade_journal.py --by-strategy       # P&L grouped by strategy
  python scripts/trade_journal.py --by-symbol         # P&L grouped by symbol
  python scripts/trade_journal.py --export trades.csv
```

**Sample output for `--by-strategy`:**
```
Strategy Performance (last 30 days)
────────────────────────────────────────────────────────────────────
Strategy               Trades  Wins  Losses  Win%   Total P&L   Avg P&L
────────────────────────────────────────────────────────────────────
ema_crossover              23    15       8  65.2%  ₹+8,420     ₹+366
rsi_reversion              18    10       8  55.6%  ₹+2,180     ₹+121
bollinger_reversion        12     5       7  41.7%  ₹-1,340     ₹-112
macd_momentum               9     6       3  66.7%  ₹+3,210     ₹+357
ml_classifier               7     5       2  71.4%  ₹+4,100     ₹+586
────────────────────────────────────────────────────────────────────
TOTAL                      69    41      28  59.4%  ₹+16,570    ₹+240
```

Implementation uses `pandas` to read the JSONL and group:
```python
df = pd.read_json("logs/trades.jsonl", lines=True)
df["pnl"] = pd.to_numeric(df["pnl"])
by_strategy = df.groupby("strategy").agg(
    trades=("pnl", "count"),
    wins=("pnl", lambda x: (x > 0).sum()),
    total_pnl=("pnl", "sum"),
    avg_pnl=("pnl", "mean"),
).reset_index()
```

### Files to change
- Create `scripts/trade_journal.py` → full query + display tool
- Edit `utils/trade_logger.py` → verify fields logged (symbol, strategy, direction, qty, entry, exit, pnl, duration_bars)
- Edit `scripts/paper_trade.py` → write to `logs/paper_trades.jsonl` on every close

### Acceptance criteria
- [ ] `trade_journal.py --by-strategy` shows correct P&L per strategy
- [ ] `trade_journal.py --days 7` filters correctly by date
- [ ] `--export trades.csv` produces a valid CSV for Excel analysis
- [ ] Works for both live trades (`logs/trades.jsonl`) and paper trades (`logs/paper_trades.jsonl`)

---

## P3-4 · Benchmark Comparison in Backtests

**Status:** ❌ Missing  
**Risk:** A backtest showing +15% return looks great until you realize Nifty 50 returned +18% in the same period. Without benchmark comparison, you cannot measure alpha or decide if a strategy adds value over simply buying an index ETF.

### Problem

`backtest_runner.py` shows absolute returns but not relative performance.
There is no way to know if the strategy is outperforming or underperforming the market.

Key metrics that require a benchmark:
- **Alpha** = strategy return − (beta × market return)
- **Beta** = correlation of strategy returns to market returns
- **Information Ratio** = active return / active risk
- **Max Relative Drawdown** = strategy DD vs. benchmark DD

### What needs to be built

**`scripts/backtest_runner.py`** — fetch Nifty 50 alongside each backtest:
```python
# Fetch benchmark
nifty_df = _fetch_ohlcv(token, "NSE_INDEX|Nifty 50", interval, days)
nifty_returns = nifty_df["close"].pct_change().dropna()
nifty_total_return = (nifty_df["close"].iloc[-1] / nifty_df["close"].iloc[0] - 1) * 100

# After each backtest result
strategy_returns = np.diff(result.equity_curve) / result.equity_curve[:-1]
beta = np.cov(strategy_returns, nifty_returns[:len(strategy_returns)])[0,1] / np.var(nifty_returns)
alpha = (total_return - nifty_total_return * beta)
```

**Display addition in `_print_result()`:**
```
  Nifty 50 Return      +18.40%    (benchmark)
  Strategy Return      +22.15%
  Alpha (vs Nifty)     + 3.75%    ← excess return
  Beta                    0.82    ← market sensitivity
  Information Ratio       1.12
```

**`analytics/factor_model.py`** already has `alpha_return` in its dataclass — wire it to the backtest output.

### Files to change
- Edit `scripts/backtest_runner.py` → fetch Nifty50 as benchmark, compute alpha/beta/IR
- Edit `analytics/factor_model.py` → verify `FactorAttribution.alpha_return` is computed correctly
- Edit `backtester/backtester.py` → expose `BacktestResult.benchmark_return` field

### Acceptance criteria
- [ ] `backtest_runner.py` shows Nifty 50 return alongside strategy return
- [ ] Alpha is correct: positive means outperforming, negative means underperforming
- [ ] Beta of a strategy that mirrors Nifty ≈ 1.0
- [ ] Works for all timeframes (not just daily)
