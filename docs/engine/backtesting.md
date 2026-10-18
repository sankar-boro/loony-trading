# Backtesting

`backtester/` replays history bar by bar through the same strategies the bot
trades, so you can see how an idea would have done before risking money — and,
with walk-forward, Monte Carlo and stress tests, how much of that result to
believe.

## Ways to run a backtest

| Tool | Best for |
|---|---|
| [Strategy Lab](../dashboard/strategy-lab.md) page / `POST /api/backtest` | One strategy, one symbol, interactive |
| `scripts/backtest_runner.py` | Several symbols, the full enabled set, trade lists, ASCII equity curves |
| `python main.py --mode backtest` | Every configured symbol with the enabled set |
| `scripts/tune_weights.py` | Backtest every strategy separately and derive weights |
| `run_pair_backtest()` / `scripts/find_pairs.py --backtest` | A pair's two legs together ([Pair Trading](strategies-stat-arb.md#backtesting-a-pair)) |
| `Backtester` in Python | Anything custom |

```bash
python scripts/backtest_runner.py --symbols RELIANCE,TCS --days 730 --trades
python scripts/backtest_runner.py --strategies donchian_breakout,zscore_reversion --monte-carlo
python scripts/backtest_runner.py --symbol INFY --walk-forward --equity-curve
```

`backtest_runner.py` options:

| Option | Default | Meaning |
|---|---|---|
| `--symbol` / `--symbols` | top 5 Nifty 50 | One symbol, or a comma-separated list |
| `--days` | 365 | Lookback in days; with `--source recorded`, the last N recorded sessions |
| `--capital` | 5,00,000 | Starting capital |
| `--timeframe` | `1d` | `1d`, `1h`, `30m`, `15m` from Upstox; `1m`–`1h` from recorded bars |
| `--source` | `upstox` | `upstox` (historical API, needs a token) or `recorded` (bars the live bot saved to `data/live_bars/`; no token) |
| `--product` | `CNC` | `MIS` applies intraday costs and the 15:14 squareoff |
| `--strategies` | your `strategies.enabled` | Names to enable |
| `--monte-carlo`, `--walk-forward`, `--trades`, `--equity-curve` | off | Extra analysis and output |
| `--token` | — | Explicit access token |

With the Upstox source it also compares each result with Nifty 50 (alpha,
beta, information ratio).

```bash
# Intraday backtest on 5-minute bars the bot recorded
python scripts/backtest_runner.py --source recorded --timeframe 5m --product MIS --symbols TCS,INFY
```

## How the simulation works

```python
from backtester import Backtester
bt = Backtester(cfg, initial_capital=500_000, product="CNC")   # or "MIS"
result = bt.run(df, "RELIANCE", engine=MetaStrategyEngine(cfg))  # or strategy=SomeStrategy(cfg)
print(result.summary())
```

For each bar *i* after the first `data.warmup_bars` (200):

1. **Exit check** (if a position is open), against bar *i*'s whole range:
   - bar **opens** beyond the stop or target (a gap) → fills at the open;
   - otherwise the **low** (long) / **high** (short) reaching the stop →
     `stop_loss` at the stop price, and the high / low reaching the target →
     `take_profit` at the target;
   - if one bar touches both, the **stop is assumed to come first**, since
     bar data cannot show which came first;
   - for MIS, a bar at or after 15:14 IST → `mis_squareoff` at the close;
   - otherwise the opening strategy's own exit rule, judged on bars up to
     this one → `strategy_exit` at the close
     ([Strategy exits](strategy-framework.md#strategy-exits)).

   Every exit pays slippage against you and the exit-side cost.
2. **Trailing stop**: if the position is still open, its stop is raised to
   `high × (1 − risk.trailing_stop_pct)` for a long (lowered to
   `low × (1 + pct)` for a short), never loosened. This mirrors the live
   `RiskManager`, which trails on every tick. Set `trailing_stop_pct: 0` to
   turn it off.
3. **Entry** (if flat; a CNC backtest never opens a short, as live —
   see [Shorts need MIS](execution.md#shorts-need-mis)): strategies see bars `0 … i−1` only — never the bar
   being traded — and the best signal (confidence × weight) is entered at bar
   *i*'s close plus slippage. MIS backtests open nothing at or after 15:14.
4. **Sizing**: risk `risk.max_risk_per_trade` of current capital over the
   distance to the stop, capped at 25 % of capital per position.
5. **Costs**: `execution.commission_delivery` (CNC, 0.21 %) or
   `commission_intraday` (MIS, 0.055 %) is a **round-trip** figure — half is
   charged on entry and half on exit — plus `execution.slippage_pct` (0.05 %)
   on each fill.

A position still open at the end closes at the last close with reason
`end_of_data`, paying the same slippage and exit cost as any other exit; the
final equity point includes it.

### Differences from live trading

| Aspect | Backtester | Live bot |
|---|---|---|
| Stop/target check | Bar high/low, stop first on a tie | Every tick |
| Trailing stop | Once per bar, from the bar's extreme | Every tick |
| Session rules | MIS squareoff only | Entry window, trade caps, cooldown, kill switch ([Intraday Session Controls](intraday-controls.md)) |
| Positions | One at a time per run | One per symbol, many symbols |
| Fill price | Next bar's close ± slippage | Market/limit fill |
| Exposure cap | 25 % of capital | `risk.max_portfolio_risk` (20 %) |

A bar that spikes through the stop and recovers stops you out, as it would
live. The trailing stop is updated only after the bar's exit check, so it
cannot stop you out on the same bar that moved it. The backtest also does not
apply the live session rules (entry window, caps, cooldown), so on intraday
bars it may take trades the live bot would refuse.

### Things that do not backtest meaningfully

- `vix_strategy`, `fii_dii` and `gift_nifty_gap` read *today's* market data
  and the wall clock, not the historical bar's.
- `vwap_reversion` and `anchored_vwap` only trade on intraday bars.
- `mtf_trend` and `order_book_imbalance` need inputs the backtester does not
  pass.

## Metrics

| Metric | Definition |
|---|---|
| `n_trades`, `win_rate` | Closed trades, % with P&L > 0 |
| `total_return_pct` | Final vs initial capital |
| `cagr_pct` | Annualised, assuming 252 bars a year (daily bars) |
| `sharpe`, `sortino` | Annualised from bar returns (√252); Sortino uses downside deviation only |
| `max_drawdown_pct` | Worst peak-to-trough fall of the equity curve (negative) |
| `profit_factor` | Gross profit ÷ gross loss |
| `avg_win`, `avg_loss`, `expectancy` | ₹ per winning / losing / average trade |
| `median_trade_return_pct` | Median per-trade return, % of entry value |
| `avg_holding_bars` | Mean bars in a trade |

Annualised figures assume daily bars; on intraday bars treat Sharpe and CAGR
as relative measures only.

## Walk-forward validation

`bt.run_walk_forward(df, symbol, engine=…, n_splits=5)` cuts the data into
five consecutive parts and runs the strategy on parts 2–5 separately, each
warming up on the bars just before it. A strategy that is good on one split
and poor on the rest is fragile.

## Monte Carlo

`backtester/monte_carlo.run_monte_carlo(trade_returns, n_simulations=1000,
method=…)` resamples per-trade **fractional** returns (0.02 = 2 %):

| Method | Resampling |
|---|---|
| `bootstrap` | Trades drawn independently with replacement |
| `block_bootstrap` | Consecutive blocks, keeping streaks together |
| `parametric` | From a normal distribution fitted to the trades |

`MCResult` gives the mean and 5th/95th percentiles of final return, maximum
drawdown and Sharpe across the simulated paths, the mean win rate, CVaR95 (the
average outcome of the worst 5 % of paths), and `p_value_sharpe` — a one-sided
t-test of whether the average trade return is above zero. Below 0.05 suggests
the edge is not just noise; with few trades, treat it with caution.

## Stress testing

`backtester/stress_test.run_stress_test(daily_pnl, capital,
max_drawdown_limit_pct=20, beta_vs_nifty=0.7)` replays your strategy's
volatility through five historical Indian crises, scaled by its Nifty beta:

| Scenario | Period |
|---|---|
| COVID crash | Feb–Mar 2020 |
| IL&FS / NBFC crisis | Sep–Oct 2018 |
| Demonetisation shock | Nov–Dec 2016 |
| China-driven crash | Aug 2015 |
| Global financial crisis | 2008 |

For each it reports the return, maximum drawdown, recovery time and whether
the strategy stayed within the drawdown limit (`survived`). `report.summary()`
returns a table; the worst scenario is flagged.

## Tuning strategy weights

```bash
python scripts/tune_weights.py --dry-run              # preview
python scripts/tune_weights.py --days 730 --min-sharpe 0.3
```

1. Fetches daily bars for ten large caps (`--symbols` to change).
2. Backtests **each strategy on its own** on every symbol and takes the median
   Sharpe.
3. Strategies below `--min-sharpe` get weight 0 and are dropped from
   `enabled`; the rest get weights proportional to their Sharpe, rescaled so
   the median weight is 1.0.
4. Writes `strategies.enabled` and `strategies.weights` to
   `config/settings.yaml`. Strategies it cannot backtest (`vix_strategy`,
   `gift_nifty_gap`, `fii_dii`, `ml_classifier`) keep their current setting
   and weight.

Weights tuned on one period can overfit it; re-tune occasionally and compare
across periods before trusting a change.

## Avoiding fooling yourself

- **Look-ahead**: strategies only ever see completed bars before the fill bar;
  `tests/test_backtest_lookahead.py` guards this.
- **Survivorship**: the universe is today's large caps — stocks that did well
  enough to be large now. Results are biased upwards.
- **Overfitting**: every parameter you tune on the same data inflates the
  result. Hold out a later period you never tune on.
- **Costs**: delivery round trips cost about 0.21 %; a strategy making 0.3 % a
  trade keeps very little.
