# Test Scenarios

A manual checklist for verifying that each part of the system works end to end
on your machine — after installing, after an upgrade, or before going live.
Automated tests are covered in [Testing](../reference/testing.md).

Tick each box as you go; most scenarios need a valid Upstox token
(`python scripts/check_token.py` shows its expiry).

## 1. Access and health

- [ ] `python scripts/check_token.py` — token valid, expiry shown as 03:30 IST,
      live prices printed.
- [ ] `python scripts/test_upstox.py --market-only` — every market-data check
      passes; note which intraday intervals return data on your account.
- [ ] `./loony.sh health` — no failures except data files that do not exist yet.
- [ ] `pytest tests/ -q --ignore=tests/test_live_upstox.py` — all pass.

## 2. Dashboard (no bot running)

```bash
./loony.sh start            # http://localhost:5163
```

| Page | Expect |
|---|---|
| Home | Index ticker live; universe with prices; signal feed after up to a minute |
| Chart | Pick RELIANCE → candles at 1D; switch to 30m → intraday candles; open "Why is it moving?" |
| Strategies | Weights and enabled list from `settings.yaml` |
| Strategy Lab | RELIANCE · `donchian_breakout` · 1Y → result with trades; repeat with Benchmark, Walk-forward and Monte Carlo on |
| Docs | Contents, search for "squareoff", follow a link between chapters |
| Positions, Trades, Daily P&L | Empty states ("Bot not running", "No paper trades yet") |

Without a token the amber **DEMO DATA** banner should appear and every page
should still render.

## 3. MarketPulse (database)

```bash
alembic upgrade head
python scripts/backfill_stocks.py
python scripts/run_signal_engine.py --limit 10
```

- [ ] **Signals** lists 10 stocks; clicking one shows the component breakdown.
- [ ] **News** → *Fetch latest news* → cards appear (demo cards without
      `NEWS_API_KEY`).
- [ ] **Copilot**: "Show bullish stocks", "Why is TCS moving?" — answers with
      evidence or an explicit "insufficient evidence".
- [ ] **Watchlists**: create one, add and remove a symbol.
- [ ] **Alerts**: create `score > 0` for the whole universe → *Evaluate now* →
      triggers listed; then delete it.
- [ ] **Intraday Lab**: scan `TCS,INFY` at 30m → results; Signals page at
      "30 min" shows them; Daily view unchanged.

Fully offline alternative: `python scripts/seed_demo_data.py` on an empty
database.

## 4. Paper trader

Smoke test (any time):

```bash
python scripts/paper_trade.py --symbols RELIANCE,TCS,HDFCBANK --tick 5 --signal-every 1 --max-positions 3
```

- [ ] Startup lists the enabled strategies and loads history for each symbol.
- [ ] Outside market hours it reports the next open and waits (Ctrl+C to stop).
- [ ] During market hours the terminal dashboard redraws every tick.
- [ ] `data/live_positions.json` and `data/equity_curve.jsonl` update; the
      dashboard's **Bot** light turns green.
- [ ] Restart within the hour → "Restored N open position(s)".

Full session during market hours:
`python scripts/paper_trade.py --symbols RELIANCE,TCS,HDFCBANK,SBIN,AXISBANK --tick 30 --signal-every 3`
— after 15:14 every position is closed (`mis_squareoff_3:14pm`); after 15:35
**Daily P&L** has today's row.

## 5. The bot in paper mode

```bash
python main.py --mode paper
```

- [ ] Outside market hours: loads history, runs one strategy pass, exits.
- [ ] During market hours: "Starting real-time WebSocket feed…", then ticks;
      `logs/trading.log` shows bars closing and signals being scored.
- [ ] Kill it (Ctrl+C) with a position open and restart → the position is
      restored.
- [ ] With `default_product: MIS`, positions close at 15:14 and no new entries
      appear afterwards.

## 6. Live mode (small size, with care)

Only after weeks of paper trading. Set `risk.max_risk_per_trade` small.

- [ ] `python main.py --mode live` with an expired token refuses to start.
- [ ] With a valid token, the startup reconciliation runs and reports no
      mismatch.
- [ ] Place an order by hand in the Upstox app → within 5 minutes an
      "untracked position" alert arrives.
- [ ] `python scripts/portfolio.py` agrees with the dashboard's Positions page.

## 7. Research tools

- [ ] `python scripts/backtest_runner.py --symbol RELIANCE --days 730 --trades --equity-curve`
- [ ] `python scripts/backtest_runner.py --symbols RELIANCE,TCS --walk-forward --monte-carlo`
- [ ] `python scripts/tune_weights.py --dry-run` — proposed weights printed,
      `settings.yaml` unchanged.
- [ ] `python scripts/train_ml.py` — evaluation report; model saved only if it
      beats the baselines.
- [ ] `python scripts/live_signals.py --symbols RELIANCE,TCS,NIFTY50 --all-signals`
- [ ] `python scripts/market_watch.py --instruments RELIANCE,TCS,INFY`
- [ ] `python scripts/option_chain.py --symbol "Nifty Bank" --strikes 8`
- [ ] `python scripts/portfolio.py` — your Upstox holdings, positions and funds.

## 8. Reports

- [ ] `python scripts/trade_journal.py --days 7 --by-strategy`
- [ ] `python scripts/strategy_report.py`
- [ ] `python scripts/daily_report.py --all`

## 9. Scheduler

Set `scheduler.enabled: true` and restart the backend.

- [ ] `curl localhost:8000/api/scheduler/status` lists `news_ingest`,
      `signal_engine`, `alert_evaluation`, `historical_backfill`, `ml_retrain`
      with next run times.
- [ ] After a few minutes `last_runs` shows successful news ingestion; during
      market hours, signal scoring and alert evaluation too.
