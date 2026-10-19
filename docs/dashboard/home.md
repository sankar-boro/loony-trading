# Home

The Home page (`/`, `pages/Dashboard.tsx`) is the at-a-glance view: index
ticker, portfolio KPIs, the equity curve, the stock universe with live prices,
and a live signal feed.

## Market ticker

The top strip shows **NIFTY50**, **BANKNIFTY** and **NIFTYIT** with last price
and percentage change, plus a **live / connecting** dot for the price stream.

It is fed by `GET /api/stream/prices`, a Server-Sent Events stream. The backend
calls Upstox's LTP endpoint for the three indices and the 30-stock watchlist
every 2 seconds (every 10 s without a valid token) and pushes one JSON
snapshot per poll:

```json
{ "watchlist": { "RELIANCE": { "ltp": 2950.4, "change_pct": 0.02 }, … },
  "market":    { "NIFTY50":  { "ltp": 24815.2, "change_pct": -0.01 }, … },
  "ts": 1791545520 }
```

> **Known limitation:** `change_pct` in this stream is the change since the
> previous poll (two seconds earlier), not since yesterday's close, so it stays
> close to zero. The day's change is available from `GET /api/watchlist` and
> `GET /api/market`. See [Project Status](../appendix/status.md).

## KPI cards

| Card | Value | Computed from |
|---|---|---|
| **Portfolio** | Latest equity, in thousands, and total return | Last point of `GET /api/equity` (`data/equity_curve.jsonl`) vs `initial_capital` |
| **Today P&L** | Cash change plus open unrealised P&L | `GET /api/positions`: `cash − initial_capital + Σ unrealised_pnl` |
| **Total Return** | % change of latest equity vs starting capital | `GET /api/equity` |
| **Win Rate** | % winning closed trades, with W/L counts | `GET /api/trades?source=paper` stats |
| **Positions** | Open positions and % of capital deployed | `GET /api/positions` |
| **Total Trades** | Closed trades and profit factor (PF) | `GET /api/trades?source=paper` stats |

Profit factor is gross profit ÷ gross loss; above 1.0 means winners outweigh
losers. All figures come from the **paper** trade log.

## Equity curve

An area chart of the portfolio value over time from `data/equity_curve.jsonl`,
down-sampled to at most 150 points, with a dashed reference line at the
starting capital. It turns green above the start and red below. When empty, it
suggests running `python scripts/seed_dashboard_data.py`, which backtests five
stocks over 180 days and writes realistic sample files for every file-based
page.

## Universe panel

The full stock universe from `GET /api/universe` (91 stocks in 18 sectors,
defined in `config/instruments.py`):

- **⭐ Watchlist** tab — the 30 default watchlist symbols (`_WATCHLIST_SYMS` in
  `dashboard/backend/config.py`), grouped by sector.
- **Sector tabs** — one per sector with its stock count.
- **Search** — filters by symbol or company name.
- Each row shows the symbol, company, **F&O** and **N50** (Nifty 50) badges, and
  the live price from the price stream.
- Click a row to open it on the [Chart](chart.md) page.

Sector groups collapse and expand when you click their header.

## Live signals feed

`GET /api/signals`, refreshed every 60 seconds. The backend fetches two years
of daily candles for ten liquid stocks (RELIANCE, TCS, HDFCBANK, SBIN,
AXISBANK, INFY, ICICIBANK, BAJFINANCE, WIPRO, TATAMOTORS), builds features,
runs the `MetaStrategyEngine` with your `config/settings.yaml`, and returns
the ten highest-confidence signals with confidence ≥ 0.40. Each card shows:

- **BUY** / **SELL** badge, symbol and price
- the strategy that produced it and a confidence bar
- stop-loss (SL) and take-profit (TP)

It returns nothing without a valid token. These are the bot's rule-based
strategy signals — for the MarketPulse composite score of every stock, see the
[Signals](signals.md) page.

When Telegram is configured, signals with confidence ≥ 0.65 are sent as a
Telegram message, each (stock, side, strategy) at most once a day, however
often the page polls. See [Avoiding noise](../operations/notifications.md#avoiding-noise).

## Refresh intervals

| Data | Interval |
|---|---|
| Price stream | push, every 2 s (10 s without token) |
| Positions | 15 s |
| Equity curve | 30 s |
| Trades stats, signals | 60 s |
