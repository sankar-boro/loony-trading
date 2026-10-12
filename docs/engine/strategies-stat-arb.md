# Statistical Arbitrage: Pair Trading

`pair_trading` · `strategies/stat_arb/pair_trading.py` · `utils/kalman.py`

Pair trading bets on the *relationship* between two related stocks rather than
on either one. When two cointegrated prices drift unusually far apart, it
sells the expensive one and buys the cheap one, expecting the gap to close.

## How it works

For a pair (A, B):

1. **Hedge ratio** — a Kalman filter (`KalmanHedgeRatio`) estimates
   `A ≈ α + β·B` bar by bar, so the ratio adapts as the relationship evolves.
   It also reports its own uncertainty.
2. **Is this a real pair?** — the first time a pair is seen, an Engle-Granger
   cointegration test must pass at p < `pair_coint_pvalue`, and the spread's
   Ornstein-Uhlenbeck **half-life** (how fast deviations decay) must lie
   between `pair_min_half_life` and `pair_max_half_life` bars. Pairs that fail
   are never traded.
3. **Spread z-score** — how many standard deviations the spread sits from its
   Kalman-smoothed mean.
4. **Signal** — the z-score is shrunk by the hedge-ratio uncertainty
   (`effective z = |z| × (1 − penalty)`). Above `pair_entry_z`:

| Spread | Leg A | Leg B |
|---|---|---|
| z > +entry (A rich vs B) | SELL | BUY |
| z < −entry (A cheap vs B) | BUY | SELL |

   Confidence = effective z ÷ 4 (max 1), reduced further by uncertainty. The two
   leg signals carry the z-score and β in their metadata. Positions are meant
   to close when |z| falls below `pair_exit_z`.

| Key | Default |
|---|---|
| `pair_entry_z` | 2.0 |
| `pair_exit_z` | 0.5 |
| `pair_coint_pvalue` | 0.05 |
| `pair_min_half_life`, `pair_max_half_life` | 5, 60 bars |
| `pair_min_history` | 120 bars |
| `pair_kalman_delta` | 1e-4 (how quickly β may change) |

Good candidate pairs in the universe include HDFCBANK/ICICIBANK, TCS/INFY,
AXISBANK/KOTAKBANK and BAJFINANCE/BAJAJFINSV — but always let the
cointegration test decide.

## Using it

Pairs need two series, so `generate_signal()` always returns nothing; use:

```python
engine = MetaStrategyEngine(cfg)
signals = engine.generate_pair_signals(
    {"HDFCBANK": df_hdfc, "ICICIBANK": df_icici},
    pairs=[("HDFCBANK", "ICICIBANK")],
)
```

`ml_models/bayesian_opt.py` has `optimize_pair_trading()` to tune the entry
and exit z-scores and lookback with Bayesian optimisation against your own
backtest function.

> **Not traded automatically.** The engine builds the strategy, but neither
> the bot, the paper trader nor the backtester calls `generate_pair_signals()`,
> and there is no configured list of pairs. Executing both legs together
> (atomically) is also not implemented. See [Project Status](../appendix/status.md).
