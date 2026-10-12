# Strategies

The Strategies page (`/strategies`, `pages/Strategies.tsx`) shows which
strategies are switched on, how much say each one has, and how each has
performed in paper trading.

## Allocation and the strategy table

Data: `GET /api/config` (every 5 minutes), which reads `config/settings.yaml`:

```json
{ "weights": { "vwap_reversion": 1.5, "bollinger_reversion": 1.2, … },
  "enabled": ["vwap_reversion", "bollinger_reversion", …],
  "capital": 500000,
  "all_strategies": ["ema_crossover", "mtf_trend", …, "ml_classifier", "pair_trading"] }
```

- **Allocation** — a donut of `strategies.weights`: each strategy's share of
  the total weight.
- **All Strategies** — every registered strategy with its weight (and a bar
  relative to the largest weight) and status **enabled** or **off**, plus the
  count "N enabled / M total".

`all_strategies` comes from `registered_strategy_names()` in
`strategies/meta_engine.py`, so it always matches what the engine can run.

What weight and enabled mean:

- **Enabled** — only strategies listed in `strategies.enabled` run. If the
  list is empty, the engine runs *every* registered strategy (the page then
  shows them all as off, because it only reads the list).
- **Weight** — multiplies a strategy's signal confidence when the engine
  ranks competing signals for a symbol. A strategy with weight 1.5 and
  confidence 0.6 beats one with weight 1.0 and confidence 0.8. Missing
  weights default to 1.0. See [The Strategy Framework](../engine/strategy-framework.md).

The header reminds you that weights are produced by
`python scripts/tune_weights.py`, which backtests each strategy and writes
weights proportional to its Sharpe ratio (see [Backtesting](../engine/backtesting.md)).

## Performance

Built from the paper trade log (`GET /api/trades?source=paper`, every 60 s),
grouped by the strategy that opened each trade:

- **Net P&L by Strategy** — horizontal bars, best to worst.
- **Performance** table — trades (N), win rate and total P&L per strategy.

With no paper trades yet the page shows **No trade data yet**. Run
`python scripts/paper_trade.py` or seed sample data with
`python scripts/seed_dashboard_data.py`.

## Changing strategies

The page is read-only. To change what runs, edit `config/settings.yaml`:

```yaml
strategies:
  enabled:
    - vwap_reversion
    - donchian_breakout
  weights:
    vwap_reversion: 1.5
    donchian_breakout: 1.2
```

The bots read the file when they start, so restart `main.py` or
`paper_trade.py` after editing. The dashboard picks the change up on its next
poll. Every strategy name is listed in the
[Configuration Reference](../reference/configuration.md) and described in the
strategy chapters of Part III.
