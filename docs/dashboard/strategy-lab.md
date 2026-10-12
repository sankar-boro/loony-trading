# Strategy Lab

The Strategy Lab (`/backtest`, `pages/Backtest.tsx`) backtests one strategy on
one symbol over historical daily bars, in the background, and shows the result
with an equity curve, trade list and optional benchmark, walk-forward and
Monte Carlo analysis.

## Running a backtest

| Control | Options | Default |
|---|---|---|
| **Symbol** | Indices and every universe stock | NIFTY50 |
| **Strategy** | Your enabled strategies (`strategies.enabled`) | The first enabled strategy |
| **Period** | 3M, 6M, 1Y, 2Y | 6M |
| **Capital** | Starting capital in ₹ | 5,00,000 |
| **Options** | Benchmark vs Nifty, Walk-forward, Monte Carlo | all off |

Press **Backtest**. The page posts to `POST /api/backtest` and gets a job id,
then polls `GET /api/backtest/{job_id}` every 1.5 s until the job is `done` or
`error`. Jobs run in a background thread pool (two workers), so several can be
queued; job results are kept in memory and lost when the backend restarts.

A valid Upstox token is required — the backend downloads the candles itself.

## What happens on the server

`_run_backtest_sync` in `dashboard/backend/routers/backtest.py`:

1. Loads `config/settings.yaml` and sets `system.mode` to `backtest`.
2. Downloads the requested period **plus enough extra history for the
   indicator warmup** (`data.warmup_bars`, default 200 bars), so the whole
   period you asked for is traded.
3. Builds features with `FeatureBuilder` (unless `feature_engineer` is false).
4. Picks the strategy: a direct strategy class for the classic strategies, or
   a `MetaStrategyEngine` restricted to that one strategy for the rest
   (microstructure, VIX, GIFT Nifty, FII/DII, ML). Either way it is the same
   code the bot runs.
5. Runs the `Backtester` (see [Backtesting](../engine/backtesting.md)) with the
   chosen capital and product (CNC unless the API request says otherwise).

## Reading the results

### Metric cards

| Metric | Meaning |
|---|---|
| **Total Return** | % change from starting capital to final equity |
| **Sharpe** | Annualised return ÷ volatility of the equity curve; above 1 is decent, above 2 is strong |
| **Max Drawdown** | Largest peak-to-trough fall of the equity curve, % |
| **Win Rate** | % of trades with positive P&L |
| **Profit Factor** | Gross profit ÷ gross loss |
| **Trades** | Number of closed trades |
| **Expectancy** | Average P&L per trade, ₹ |
| **Median Trade** | Median per-trade return, % — less distorted by one big winner than the average |
| **Avg Holding** | Average bars a trade was held |

### Charts and trade list

- **Equity curve** — portfolio value bar by bar, green if the period ended up.
- **P&L Distribution** — histogram of trade P&L in 16 bins.
- **Trades** — direction, entry and exit price, bars held, P&L and the exit
  reason, colour-coded: `stop_loss` red, `take_profit` green, `mis_squareoff`
  amber (an intraday position forced shut at 15:14), `end_of_data` grey
  (still open when the data ran out).

### Benchmark

With **Benchmark** on, Nifty 50 is fetched for the same period and compared:

| Field | Meaning |
|---|---|
| Nifty | Nifty 50 return over the period |
| Return | The strategy's return |
| Beta | Sensitivity of the strategy's daily returns to Nifty's |
| Alpha | Strategy return − beta × Nifty return: what it earned beyond market exposure |
| Info Ratio | Alpha ÷ annualised tracking error |

### Walk-forward

With **Walk-forward** on, the data is cut into 5 equal consecutive parts and
the strategy is run separately on parts 2–5 (part 1 is never tested on its
own; each tested part warms its indicators up on the bars just before it). The
table lists each split's return, Sharpe, max drawdown and trades; the cards and
charts show the last split. A strategy whose good
result comes from one lucky split is not robust.

### Monte Carlo

With **Monte Carlo** on, the trade returns are resampled 500 times (bootstrap)
to estimate how much of the result is luck: the mean and 5th–95th percentile
Sharpe, mean and 95th-percentile max drawdown, mean return, and a p-value from
a one-sided t-test of whether the average trade return is above zero (shown as
a percentage). Lower is better; below 5 % is conventionally significant.

## The API directly

Everything the page does is available over HTTP, including things the page
does not expose (several symbols at once, several strategies through the meta
engine, MIS product, timeframes, risk overrides):

```bash
curl -X POST localhost:8000/api/backtest -H 'Content-Type: application/json' -d '{
  "symbols": ["RELIANCE", "TCS"],
  "strategies": ["vwap_reversion", "donchian_breakout"],
  "days": 365, "timeframe": "1d", "product": "MIS",
  "risk": {"max_risk_per_trade": 0.005},
  "benchmark": true, "monte_carlo": true
}'
curl localhost:8000/api/backtest/<job_id>
```

All request fields are listed in the [REST API Reference](../reference/rest-api.md).
For longer research, use `scripts/backtest_runner.py` and `scripts/tune_weights.py`
([Command-Line Tools](../operations/cli.md)).
