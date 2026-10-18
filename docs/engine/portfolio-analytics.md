# Portfolio and Analytics

Portfolio-level tracking and analysis: the portfolio manager the bot uses,
plus beta hedging, factor decomposition and stress testing for the current
holdings, shown on the [Portfolio Risk](../dashboard/portfolio-risk.md)
page.

## PortfolioManager

`portfolio_manager/portfolio.py`, used by `main.py`:

| Method | Purpose |
|---|---|
| `update_price(symbol, price)` | Keeps the last 200 observed prices per symbol |
| `is_correlated(symbol, open_symbols)` | True if the 30-observation return correlation with any open position exceeds `portfolio.correlation_limit` (0.7); needs ≥ 10 prices for both. The bot skips the entry |
| `record_trade(symbol, pnl, strategy)` | Updates capital, equity curve, returns and the trade log |
| `max_allocation(symbol, allocations)` | Capital still available under the 20 % exposure cap |
| `metrics()` | Total return, capital, trades, win rate, Sharpe, max drawdown, profit factor |

Correlation here uses the bot's own observed prices, so it only kicks in once
a session has accumulated enough ticks.

```yaml
portfolio:
  initial_capital: 500000
  base_currency: INR
  rebalance_interval_hours: 24
  correlation_limit: 0.7
```

## Beta-neutral hedging

`portfolio_manager/beta_neutral.py` (`BetaNeutralPortfolio`). A long book
loses when Nifty falls, whatever the stock picks. Hedging with short Nifty
futures leaves only stock-specific returns:

1. `compute_beta(symbol, prices)` — rolling OLS beta of each stock against
   Nifty (with R² for quality).
2. `portfolio_beta(positions)` — Σ (position value ÷ capital) × β.
3. `compute_hedge(positions, nifty_spot)` — Nifty futures lots to short (or
   buy) to bring the beta to zero, capped at a maximum share of capital; uses
   the Nifty lot size from `FO_LOT_SIZES` (65) and ~12 % futures margin.
4. `beta_summary(positions)` — betas, portfolio beta and the current hedge.

The Portfolio Risk page shows the betas and the suggested hedge
(`analytics/portfolio_analytics.py`). The bot does not place hedges
automatically.

## Factor model

`analytics/factor_model.py` (`FactorModel`) explains returns with a ridge
regression on Indian index factors — market (Nifty 50), banking, IT, FMCG,
auto and midcap (size):

```python
fm = FactorModel()
exposure = fm.fit(portfolio_returns, factor_returns)   # alpha (annualised), betas, R², IR
fm.decompose_return(...)                             # how much of a return came from each factor
fm.sector_exposure(positions); fm.hedge_suggestion(...)
```

A high R² with little alpha means returns are mostly market and sector
exposure, not skill. `sector_exposure` maps holdings to factor sectors using
the universe's sectors (Banking and Finance → banking, IT, FMCG,
Automobile → auto). Before 2026-10-18 it used its own short hard-coded list
with a wrong ticker.

## Current-holdings analytics

`analytics/portfolio_analytics.analyse(positions, capital, fetch_daily)`
combines the three for the open positions, at their signed market values,
over the last year of daily bars:

| Section | From |
|---|---|
| `beta` | Per-stock beta (120 days), portfolio beta, rupee beta exposure, a futures `hedge` or a `hedge_note` saying why none is suggested |
| `factors` | Holdings-weighted daily returns regressed on the six factor indices: loadings, t-statistics, R², annual alpha, residual volatility, sector exposure, hedge suggestion |
| `stress` | `run_stress_test` with the portfolio beta × gross ÷ capital |

`GET /api/portfolio/analytics` serves it to the Portfolio Risk page.

## Per-strategy P&L

The live bot books every closed trade against its strategy and switches off
a strategy that loses too much in a day or too many trades in a row
([Strategy limits](intraday-controls.md#strategy-limits)). Today's P&L per
strategy is on the [Intraday Desk](../dashboard/intraday-desk.md).
(`analytics/live_pnl.py`, an earlier unconnected version of these limits,
was removed.)

## Performance metrics

`utils/math_utils.py` holds the shared formulas used by the backtester and
portfolio manager: `sharpe_ratio`, `sortino_ratio`, `max_drawdown`,
`profit_factor`, `rolling_zscore`, `safe_divide`, `clamp`, `pct_change`.
