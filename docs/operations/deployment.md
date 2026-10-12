# Deployment

Ways to run Loony Trading continuously: Docker Compose for everything, or
systemd services on a Linux machine. Either way, three things run: PostgreSQL,
the dashboard backend (with the scheduler) and a trading process.

## Docker Compose

```bash
cp .env.example .env          # fill in your keys
docker compose up -d
docker compose logs -f
docker compose ps             # health status
```

| Service | Image / command | Port | Notes |
|---|---|---|---|
| `db` | `postgres:16-alpine` | 5432 | Data in the `loony-pgdata` volume; healthcheck `pg_isready` |
| `redis` | `redis:7-alpine` | 6379 | Provisioned for future caching; not required by current code |
| `dashboard` | `uvicorn dashboard.backend.main:app --workers 1` | 8000 | Serves the API **and** the built React app; healthcheck `GET /api/health` |
| `bot` | `python scripts/paper_trade.py` | — | Paper trading; healthcheck: `live_positions.json` saved within 5 minutes |

The image (`Dockerfile`, Python 3.11) installs the Python requirements, builds
the frontend with npm and copies the project. `logs/`, `data/`, `models/` and
`config/` are mounted from the host, so state, tokens and settings survive
rebuilds. Inside Compose the services reach Postgres at host `db`
(`DATABASE_URL` is set accordingly).

After the first start, create the schema and load data:

```bash
docker compose exec dashboard alembic upgrade head
docker compose exec dashboard python scripts/backfill_stocks.py
```

**One worker.** Each backend worker starts its own scheduler, so the dashboard
must run with a single uvicorn worker when `scheduler.enabled` is true —
otherwise every job runs once per worker.

**Live trading in Docker**: change the bot's command to
`python main.py --mode live`. The token still has to be renewed daily, which
needs a browser or phone approval — run `scripts/upstox_login.py` on the host
(it writes into the mounted `data/`) and restart the bot.

The health endpoint returns 200 when healthy and 503 otherwise:

```json
{ "status": "healthy",
  "checks": { "token": "ok (6.2h)", "equity_data": "ok", "positions_data": "ok",
              "strategy_engine": "ok", "ml_model": "not trained" } }
```

## systemd (bare metal)

A typical layout under `/opt/loony-trading` with a virtualenv in `.venv`.

**Dashboard + scheduler** — `/etc/systemd/system/loony-dashboard.service`:

```ini
[Unit]
Description=Loony Trading dashboard
After=network-online.target postgresql.service

[Service]
WorkingDirectory=/opt/loony-trading
EnvironmentFile=/opt/loony-trading/.env
ExecStart=/opt/loony-trading/.venv/bin/uvicorn dashboard.backend.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Build the frontend once (`cd dashboard/frontend && npm run build`); the backend
then serves it.

**Trading bot** — `/etc/systemd/system/loony-bot.service`, same pattern with:

```ini
ExecStart=/opt/loony-trading/.venv/bin/python main.py --mode live
Restart=on-failure
```

**Daily token renewal** — set `SERVICE_NAME=loony-bot` in
`scripts/auto_login.sh` so a successful renewal restarts the bot, and add the
cron entry from [Connecting to Upstox](../getting-started/upstox-access.md#renewing-automatically-every-morning).

Restarting the bot is safe: it restores its positions from
`data/live_positions.json` and, in live mode, reconciles them with Upstox
([Position Safety](../engine/position-safety.md)).

```bash
sudo systemctl enable --now loony-dashboard loony-bot
journalctl -u loony-bot -f
```

## Security checklist

- Expose port 8000 only on a private network or behind a reverse proxy with
  authentication — **the dashboard has no login**, and its API can trigger
  backtests, alert evaluations and news ingestion.
- Keep `.env` and `data/` readable only by the service user (`chmod 600 .env`).
- CORS allows only the local development origins
  (`localhost:5163/5174/5175/3000`); add your own origin in
  `dashboard/backend/main.py` if you serve the frontend from elsewhere.
- Back up the database and the files listed in
  [Logs and Data Files](logs-and-data-files.md#backing-up).
