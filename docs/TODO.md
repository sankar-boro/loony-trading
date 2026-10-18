# TODO

Everything still to do, grouped by priority. Section 1 covers the items
that protect real money, so do those first. It combines the open items in
[Project Status](appendix/status.md) with a scan of the code on 2026-10-18.

Suggested order: section 1, then items 33–36, then items 9–12. Each of those
groups is self-contained.

## 1. Before trading real money

1. **Dashboard login.** The dashboard has no login at all. Anyone who can
   reach port 8000 can press **Flatten all**, pause the bot or read your
   positions.
2. **Lock down the Docker ports.** Docker Compose publishes Postgres (5432),
   Redis (6379) and the dashboard (8000) on every network interface. Bind
   them to `127.0.0.1` or put them behind a proxy.
3. **Test exchange stops with one share.** The stop orders held at Upstox
   are only tested against fakes. Try them on a live one-share position
   before turning them on.
4. **Make index signals tradable.** `vix_strategy`, `fii_dii` and
   `gift_nifty_gap` signal on NIFTY/BANKNIFTY, which can't be bought as a
   stock. Map them to futures or an ETF, or stop them generating orders.
5. **Re-tune strategy weights.** The current enabled list and weights came
   from backtests with known bugs: VWAP firing on every bar, double-counted
   costs, close-only stops.
6. **Retire the separate paper trader.** `scripts/paper_trade.py` is a
   1,000-line second copy of the bot. It has none of the intraday session
   rules, uses a flat 0.1 % charge, and closes everything at 15:14. Make
   paper mode `main.py --mode paper` and delete or slim the script.
7. **Stop repeated notifications.**
   - `/api/signals` sends Telegram messages on every call, so an open Home
     page repeats them every minute.
   - Alerts have no cooldown.
   - The notifier has no rate limit.

8. ~~**No shorts in delivery.**~~ **Done 2026-10-18.** SELL never opens a
   short on CNC in the executor, the bot or the backtester; see
   [Shorts need MIS](engine/execution.md#shorts-need-mis).

## 2. Trading correctness

9. **Session rules in backtests.** Apply the entry window, trade caps,
   cooldown and kill switch, so intraday backtests match what the live bot
   would do.
10. **One position-size cap.** The backtester caps a position at 25 % of
   capital, but live uses `risk.max_portfolio_risk` (20 %).
11. **Close button per position.** The Intraday Desk only has Flatten all.
12. **Adopt manual broker positions.** Positions opened by hand at the
    broker are alerted, not tracked.
13. **Options.**
    - Strategies are not in the engine.
    - The resolver builds name-based keys, but real Upstox F&O keys are
      numeric.
    - F&O STT is not in the charges model.
14. **Expiry-day strategy.** `ExpiryDayStrategy` assumes weekly BankNifty
    expiries, which NSE ended in 2024.
15. ~~**Pair trading.**~~ **Done 2026-10-18** (intraday on MIS); see
    [Pair Trading](engine/strategies-stat-arb.md).
16. **Unwired code.** These pieces are written but nothing calls them:
    - CVaR limits, circuit-breaker checks, TWAP/VWAP execution (beta,
      factors and stress tests are now on the Portfolio Risk page);
    - the delivery-% signal and FII/DII size multipliers.
17. **Crypto executor retries.** `execution_engine/executor.py` still
    retries order placement, which can duplicate orders.

## 3. Strategies, data and ML

18. **Strategies that can never fire.** `order_book_imbalance` gets no order
    book, `mtf_trend` gets no multi-timeframe data, and PEAD has no earnings
    data.
19. **GIFT Nifty has no data source.** `gift_nifty_gap` is enabled but
    effectively inactive.
20. **5- and 15-minute bars.** Upstox refuses them on this account. The bot
    now records its own 1-minute bars
    ([Recording live bars](engine/intraday-controls.md#recording-live-bars));
    use them to give the live bot 5/15-minute history.
21. **Macro strategy backtests.** VIX, FII/DII and GIFT read today's data,
    so their backtests are meaningless. They need historical data, read as
    it was on each day.
22. ~~**Regimes.**~~ **Done 2026-10-18:** gated HMM fitting, breakout and
    crisis regimes; see [Market regimes](engine/strategy-framework.md#market-regimes).
23. ~~**Strategy parameters.**~~ **Done 2026-10-18:** `strategies.params`,
    see [Where parameters come from](engine/strategy-framework.md#where-parameters-come-from).
24. **ML.**
    - No model with a real edge yet: the last run reached 40.9 % accuracy
      against a 48.7 % baseline.
    - `train_ml.py` skips the split/bonus price adjustment.
    - Features attach today's macro values to every historical row.
    - The drift detector is not connected to retraining, and the RL agent
      is a skeleton.
25. **Data feeds.**
    - No earnings calendar.
    - The FII/DII scrape should run after NSE publishes (about 17:30).
    - BSE lot sizes (SENSEX, BANKEX) need re-checking.

## 4. Dashboard and MarketPulse

26. **Wrong change %.** The price stream's `change_pct` is measured against
    the price two seconds earlier, so Home and Chart show about 0 %.
27. **Mislabelled "catalyst".** News cards show `impact_score × 10` under
    that name.
28. **Stale daily P&L.** Portfolio Risk's daily P&L shows yesterday's figure
    until today's report is written.
29. **Missing tools.** No paper-order button; the chart drawing tools are
    visual only; no live price line.
30. **Claude model.** `ANTHROPIC_MODEL` defaults to `claude-opus-5`;
    `claude-opus-5-5` is newer and cheaper.
31. **Dead code.** `dashboard/backend/routers/backtest.safe.py` is unused.
32. **Large frontend bundle.** One 1 MB JavaScript file; split it per page.

## 5. Code health and infrastructure

33. **Hard-coded symbol lists.** Nine places keep their own stock lists, the
    same problem already fixed for ISINs:
    - `DEFAULT_SYMBOLS` in `train_ml.py`, `backtest_runner.py`,
      `live_signals.py`, `paper_trade.py`, `tune_weights.py` and
      `seed_demo_data.py`;
    - `SYMBOLS` in `seed_dashboard_data.py`;
    - `_WATCHLIST_SYMS` in `dashboard/backend/config.py`.

    Derive them from `config/instruments.py`.
34. **Swallowed errors.** 120 bare `except Exception:` blocks hide failures;
    log them or narrow them.
35. **No CI.** No GitHub Actions, linter (ruff), type checker or pre-commit
    hooks. Tests only run when someone remembers.
36. **Unpinned dependencies.** None of the 60 entries in `requirements.txt`
    pins a version. Pin them, and split runtime from dev (pytest).
37. **No frontend tests.**
38. **Paths and ports.**
    - `logs/trading.log` depends on the directory you start from
      (`models/hmm/` is fixed).
    - `loony.sh status` hard-codes port 8000.
39. **Missing reports and tests.** No walk-forward optimisation pipeline or
    execution-quality report, and `ModelTrainer` is only tested indirectly.
40. **Manual docs refresh.** The handbook's Postgres copy only updates when
    you run `scripts/migrate_docs.py`. Run it at dashboard start or in CI.
41. **Uncommitted `config/settings.yaml` edit.**
    - A formatter collapsed the comment alignment.
    - It turned two values into multi-line YAML.
    - It switched `scheduler.enabled` to `true`.

    Commit or revert it deliberately.
