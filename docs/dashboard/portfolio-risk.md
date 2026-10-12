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
