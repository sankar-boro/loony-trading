# Statistical Arbitrage: Pair Trading

`pair_trading` · `strategies/stat_arb/pair_trading.py` · `utils/kalman.py` ·
`backtester/pair_backtester.py` · `scripts/find_pairs.py`

Pair trading bets on the *relationship* between two related stocks rather than
on either one. When two cointegrated prices drift unusually far apart, it
sells the expensive one and buys the cheap one, expecting the gap to close.

## How a pair is evaluated

`PairTradingStrategy.evaluate()` looks at the last `pair_lookback` aligned
closes of A and B and returns a `PairState`. It is **stateless**: the same
bars always give the same answer, and a backtest never sees the future.

1. **Hedge ratio.** An OLS fit `A ≈ α + β·B` over the window
   (`pair_hedge: ols`, the default). With `pair_hedge: kalman`, a Kalman
   filter seeded from the OLS fit lets β drift through the window. Its
   observation noise is set to the spread's variance, so β cannot chase each
   bar and absorb the spread being traded.
2. **Spread z-score.** The latest spread `A − (β·B + α)` in standard
   deviations of the window's spreads.
3. **Is this a real pair?** Engle-Granger cointegration: an augmented
   Dickey-Fuller test on the spread, compared with MacKinnon critical values
   (−3.90 / −3.34 / −3.04 at 1 / 5 / 10 %, chosen by `pair_coint_pvalue`).
   The spread's Ornstein-Uhlenbeck **half-life**, how many bars a deviation
   takes to halve, must lie between `pair_min_half_life` and
   `pair_max_half_life`, and β must be positive. A pair failing any test is
   marked not tradable, with the reason. These statistics are computed in
   numpy (`utils/kalman.py`), with no statsmodels dependency.

| Spread | Leg A | Leg B | Spread position |
|---|---|---|---|
| z > +`pair_entry_z` (A rich vs B) | SELL | BUY | −1 |
| z < −`pair_entry_z` (A cheap vs B) | BUY | SELL | +1 |

**Exits** (`exit_reason`) close both legs:
- the spread reverts inside ±`pair_exit_z`;
- or it stretches further to ±`pair_stop_z` against you;
- or `max_hold_bars` passes.

**Sizing** (`leg_quantities`): leg A gets `pair_capital_pct` of capital, and
leg B gets β times as many shares, so the pair is hedge-ratio neutral.

Confidence scales from 0.55 at `pair_entry_z` to 0.85 at `pair_stop_z`. Each
leg signal carries the z-score, β, half-life and ADF statistic in its
metadata. The legs' own stops (`pair_leg_stop_pct`, 6 %) are only disaster
stops; the pair is managed on its spread.

| Key (`strategies.params.pair_trading`) | Default |
|---|---|
| `pair_entry_z`, `pair_exit_z`, `pair_stop_z` | 2.0, 0.5, 4.0 |
| `pair_lookback` | 250 bars |
| `pair_min_history` | 120 bars |
| `pair_coint_pvalue` | 0.05 |
| `pair_min_half_life`, `pair_max_half_life` | 2, 60 bars |
| `pair_hedge` | `ols` (or `kalman`) |
| `pair_kalman_delta` | 1e-5 (how quickly β may drift, Kalman only) |
| `pair_capital_pct` | 0.10 of capital in leg A |
| `pair_leg_stop_pct`, `pair_leg_target_pct` | 0.06, 0.20 |
| `max_hold_bars` | 0 (off) |

## Finding pairs

```bash
python scripts/find_pairs.py                                  # every sector, 1 year of daily bars
python scripts/find_pairs.py --sectors Banking,IT --days 730 --backtest
python scripts/find_pairs.py --symbols HDFCBANK,ICICIBANK,AXISBANK,KOTAKBANK
```

For every two stocks in the same sector of `config/instruments.py`, it runs
the same tests the strategy uses. It reports the ADF statistic, half-life,
β, correlation and today's z-score, and with `--backtest` the pair
backtest's trades, return and Sharpe. Each pair is tested in the
orientation with the stronger statistic. It prints a `pairs:` block for the
ones that pass. Needs an Upstox token, or the candle cache, for daily bars.

Pairs come and go. A scan on 2026-10-18 found none of the big private and PSU
banks cointegrated over the previous year. Re-run the scan before trading a pair.

## Backtesting a pair

```python
from backtester.pair_backtester import run_pair_backtest
result = run_pair_backtest(df_a, df_b, "TCS", "INFY", cfg, initial_capital=500_000)
print(result.summary())
for t in result.pair_trades: ...      # legs, quantities, entry/exit z, reason
```

On each bar the strategy is evaluated on the closes up to that bar, and
entries and exits fill at that close with `execution.slippage_pct` against
you on both legs. Each leg pays `execution.commission_futures` (round trip,
default 0.06 %), because holding a short overnight in India means futures. A
pair still open at the end closes as `end_of_data`. Metrics are the usual
ones ([Backtesting](backtesting.md#metrics)); a trade's return is its P&L
over the pair's gross notional.

## Live trading

List pairs under `strategies.pairs` (empty by default, so nothing trades):

```yaml
strategies:
  pairs:
    - [TCS, INFY]
```

On every closed bar of either leg, the bot evaluates the pair. It uses
intraday bars when both legs have them, else daily.

- **Opening.** The pair must be tradable and past `pair_entry_z`. Neither
  stock may already be held, and the
  [session rules](intraday-controls.md#session-rules) must allow both
  stocks. The sector must have room for the gross amount. Leg A is placed
  first, then leg B. If B does not fill, A is closed straight away
  (`pair_unwind`), so the bot never holds half a hedge. Both positions get
  the same `pair_id`, saved with the positions.
- **Product.** A pair always has a short leg, so it needs a product that can
  hold one ([Shorts need MIS](execution.md#shorts-need-mis)). On CNC the bot
  logs a `block` event instead. On MIS, pairs are intraday and closed by the
  15:14 squareoff.
- **Closing.** Spread exits close both legs (`pair_exit (…)`). If one leg
  closes on its own, for example its disaster stop, the other is closed too
  (`pair_leg_closed (…)`). The squareoff, kill switch and flatten close
  everything as usual.
- **Other strategies leave pair legs alone.** A signal on a stock held as a
  pair leg is ignored rather than treated as a reversal.

`ml_models/bayesian_opt.py` has `optimize_pair_trading()` for tuning the
z-score thresholds against your own backtest function.

## Limits

- Overnight pairs need futures, and F&O contract resolution is not built yet
  ([TODO](../TODO.md) item 13). Until then, live pairs are intraday on MIS.
- Leg B is placed after leg A fills, not in one basket order. A partial fill
  of B leaves the hedge slightly off.
