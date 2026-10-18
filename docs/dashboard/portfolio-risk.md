# Portfolio Risk

The Portfolio Risk page (`/risk`, `pages/PortfolioRisk.tsx`) analyses the open
positions of the active bot: how much capital is exposed, where it is
concentrated, how correlated the holdings are, and whether any risk limit has
been crossed. It refreshes every 15 seconds from `GET /api/portfolio/risk`.

## Metrics

| Metric | Definition |
|---|---|
| **Capital** | `initial_capital` from the bot's state file |
| **Cash** | Uninvested cash |
| **Market Value** | Σ size × current price of open positions |
| **Exposure** | Market value ÷ capital |
| **Daily P&L** | Realised P&L of the latest `data/daily_pnl.jsonl` record + current unrealised P&L |
| **Unrealized P&L** | Σ unrealised P&L of open positions |
| **Max Loss (at stops)** | Σ (distance from entry to stop × size): what you lose if every stop is hit |
| **Open Positions** | Count |

> **Known limitation:** "Daily P&L" adds the *latest* daily record's realised
> P&L, which is yesterday's until today's end-of-day report is written.

## Sector exposure

A bar per sector (from `config/instruments.py`) showing position value as a
percentage of capital.

## Position correlation

A heat-map of the pairwise correlation of daily returns over the last 90 days
between every open position (needs two or more). Values near +1 mean the
positions move together — little diversification. Prices come through
`UpstoxDataEngine`, so the matrix works in demo mode too; a symbol whose data
cannot be fetched is left out rather than failing the page.

## Warnings

| Warning | Severity | Fires when |
|---|---|---|
| Sector concentration | warning | A sector exceeds 35 % of capital |
| High correlation | warning | Two positions correlate at 0.70 or more |
| Total exposure | warning | Market value exceeds `risk.max_portfolio_risk` (default 20 %) of capital |
| Daily loss limit | critical | Daily P&L is below −`risk.max_daily_drawdown` (default 5 %) of capital |

The page is a monitor — it does not stop trading. The bots enforce the limits
themselves; see [Risk Management](../engine/risk-management.md).

## Beta, factors and stress tests

When positions are open, three more panels load from
`GET /api/portfolio/analytics`. That endpoint is slower, because it fetches
a year of daily bars (cached), and refreshes every 5 minutes. All three
treat the current positions as if they had been held over that year; shorts
count negative.

- **Market beta** — each stock's beta against Nifty 50 (120 days, with R²),
  the portfolio beta and the rupee beta exposure. If the beta is beyond
  ±0.15 and large enough, it suggests a Nifty futures hedge (direction and
  lots). Otherwise it says why not, for example that the exposure is
  smaller than one futures lot.
- **Factor exposures** — loadings on Nifty 50, Bank Nifty, Nifty IT, FMCG,
  Auto and Midcap 150 (hover for the t-statistic), with R², annual alpha and
  residual volatility. A sector-concentration hedge is suggested when one
  factor sector holds more than 35 % of the book.
- **Crisis stress test** — the COVID crash, the IL&FS crisis, the 2015 China
  crash, the 2008 crisis and demonetisation, replayed on the book. The
  replay uses the portfolio beta scaled by the share of capital invested.
  It shows return, maximum drawdown and pass/fail against a 20 % drawdown
  limit; the worst scenario is in red.

See [Portfolio and Analytics](../engine/portfolio-analytics.md).
