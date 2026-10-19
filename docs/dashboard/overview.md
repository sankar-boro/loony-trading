# Dashboard Overview

The dashboard is a single-page React app (`dashboard/frontend/`) talking to a
FastAPI backend (`dashboard/backend/`). This chapter explains the layout, how
data reaches each page, and the conventions shared by every page. The chapters
that follow cover each page in turn.

## Layout

```
┌───────────────┬──────────────────────────────────────────────────┐
│ ▲ LOONY       │ ⚠ DEMO DATA — only shown without an Upstox token │
│   TRADING     ├──────────────────────────────────────────────────┤
│               │                                                  │
│ ◈ Dashboard   │                                                  │
│ ◌ Chart       │                page content                      │
│ ◎ Positions   │                                                  │
│ …             │                                                  │
│ ¶ Docs        │                                                  │
│               │                                                  │
│ ● Market  42m │                                                  │
│ ● Bot running │                                                  │
│ ● Token  6h   │                                                  │
└───────────────┴──────────────────────────────────────────────────┘
```

The sidebar (`components/Layout.tsx`) lists every page. Its footer polls
`GET /api/status` every 10 seconds:

| Indicator | Source | Meaning |
|---|---|---|
| **Market** | `is_market_open()`, `minutes_to_close()`, `next_market_open()` | Green + minutes left while NSE is open; otherwise the next open time |
| **Bot** | `saved_at` in `data/live_positions.json` | Green if a bot (`paper_trade.py` or `main.py`) saved its state within the last 300 s |
| **Token** | `data/upstox_token.json` / `UPSTOX_ACCESS_TOKEN` | Green + age while the token is before its 03:30 IST expiry; red "missing" otherwise |

When the token is missing or expired, `demo_mode` is true and the amber
**DEMO DATA** banner explains that prices, signals and history are synthetic.

## Pages

| Page | Route | Chapter |
|---|---|---|
| Dashboard | `/` | [Home](home.md) |
| Intraday Desk | `/desk` | [Intraday Desk](intraday-desk.md) |
| Chart | `/chart` | [Chart](chart.md) |
| Positions, Trades, Daily P&L | `/positions`, `/trades`, `/daily` | [Positions, Trades and Daily P&L](positions-trades-pnl.md) |
| Strategies | `/strategies` | [Strategies](strategies.md) |
| Backtest (Strategy Lab) | `/backtest` | [Strategy Lab](strategy-lab.md) |
| News | `/news` | [News](news.md) |
| Signals | `/signals` | [Signals](signals.md) |
| Copilot | `/copilot` | [Copilot](copilot.md) |
| Watchlists, Alerts | `/watchlists`, `/alerts` | [Watchlists and Alerts](watchlists-alerts.md) |
| Portfolio Risk | `/risk` | [Portfolio Risk](portfolio-risk.md) |
| Intraday Lab | `/intraday` | [Intraday Lab](intraday-lab.md) |
| Docs | `/docs/*` | [The Docs Reader](docs-reader.md) |

## Signing in

On the machine it runs on, the dashboard opens straight away. From anywhere
else it shows a login screen, which works only once `DASHBOARD_PASSWORD` is
set on the server. **Sign out** is at the bottom of the sidebar. An expired
session returns you to the login screen. See
[Dashboard login](../operations/deployment.md#dashboard-login).

## Where the data comes from

Pages get their data from three kinds of source, and knowing which explains
most "why is this empty?" questions:

| Source | Written by | Read by | Needs |
|---|---|---|---|
| **Files** in `data/` and `logs/` | `paper_trade.py`, `main.py`, `seed_dashboard_data.py` | Home, Intraday Desk, Positions, Trades, Daily P&L, Strategies, Portfolio Risk | A bot run (or the seed script) |
| **Upstox API** (live calls from the backend) | — | Home ticker and universe prices, Chart, Strategy Lab, the live signal feed | A valid token (otherwise demo data or empty) |
| **PostgreSQL** | News pipeline, signal engine, scheduler, your watchlists/alerts | News, Signals, Copilot, Watchlists, Alerts, Intraday Lab, the Chart's "why" panel | `alembic upgrade head` and data (see [Installation](../getting-started/installation.md)) |

The files are listed with their formats in
[Logs and Data Files](../operations/logs-and-data-files.md); the database in
[The Database](../marketpulse/database.md).

## How the frontend talks to the backend

- **REST** — every page calls endpoints under `/api/…` (see the
  [REST API Reference](../reference/rest-api.md)). Most use
  [SWR](https://swr.vercel.app/) (`useSWR`) with a `refreshInterval`, so they
  poll on their own; each chapter lists its page's polling intervals.
- **Server-Sent Events** — `GET /api/stream/prices` pushes a price snapshot
  every 2 s (10 s without a token) to the Home page and the Chart page.
- In development, Vite proxies `/api` and `/ws` from :5163 to the backend on
  :8000 (`vite.config.ts`). In production the backend serves the built app
  itself: `/assets` from `frontend/dist/assets`, and every other non-API path
  returns `index.html` so client-side routes like `/docs/...` work on reload.

## Building and changing the frontend

| Task | Command (in `dashboard/frontend/`) |
|---|---|
| Dev server with hot reload | `npm run dev` |
| Type-check and production build | `npm run build` (`tsc && vite build` → `dist/`) |

The stack: React 18, React Router 6, SWR, Tailwind CSS 3 (colour tokens such as
`bg`, `surface`, `border`, `dim`, `green`, `red`, `amber`, `blue` are defined in
`tailwind.config.js`), Recharts for charts, `lightweight-charts` for candles,
and `react-markdown` for this handbook. Shared API types live in
`src/types.ts` and the API client in `src/api.ts`.

To add a page: create `src/pages/MyPage.tsx`, add a `<Route>` in `src/App.tsx`
and an entry in the `NAV` list in `src/components/Layout.tsx`.
