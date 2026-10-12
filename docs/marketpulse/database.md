# The Database

MarketPulse stores its data in PostgreSQL through SQLAlchemy 2.0. The models
(`db/models.py`) use only portable column types (`String`, `JSON`,
`DateTime`, a non-native `Enum`), so the same code runs on PostgreSQL in
production and SQLite in tests.

## Connecting

`db/base.py` loads `.env` and creates the engine from the first of:

1. `DATABASE_URL`, a full SQLAlchemy URL;
2. `DB_NAME`, `DB_HOST`, `DB_PORT` (5432), `DB_USERNAME`, `DB_PASSWORD`;
3. `postgresql+psycopg2://loony:loony@localhost:5432/loony_trading`, the
   docker-compose `db` service as seen from your machine. Inside Compose the
   services use host `db` instead.

With `DB_SCHEMA` set (for example `basic`), every connection uses that schema
as its `search_path`, so all tables live there instead of in `public`.
`alembic upgrade head` creates the schema if it can and keeps its
`alembic_version` table there too. A role that does not own the database
cannot create schemas, so the owner or a superuser has to create it once:

```bash
sudo -u postgres psql -d loony_trading -c "CREATE SCHEMA basic AUTHORIZATION <user>;"
```

| Helper | Use |
|---|---|
| `get_db()` | FastAPI dependency: `db: Session = Depends(get_db)` |
| `session_scope()` | Context manager for scripts and jobs; commits on success, rolls back on error |

## Tables

### Reference data

**`stocks`** — the universe. One row per symbol, loaded from
`config/instruments.py` by `scripts/backfill_stocks.py` (safe to re-run; it
upserts).

| Column | Notes |
|---|---|
| `symbol` | Unique, e.g. `RELIANCE` |
| `exchange` | `NSE_EQ` |
| `company_name`, `sector`, `industry`, `isin`, `market_cap` | From the universe file; `market_cap` is a tier (Large/Mid/Small Cap) |
| `is_active` | Always true today |

### Market data

**`price_bars`** — OHLCV bars per stock, timestamp and timeframe (unique on
all three), with optional VWAP. The table exists in the schema but current code
fetches candles live from Upstox instead of storing them.

### News

| Table | One row per | Key columns |
|---|---|---|
| `news_articles` | Fetched article | `source`, `title`, `url`, `published_at`, `content`, `hash` (SHA-256 of source + title + URL; unique, the deduplication key) |
| `news_events` | Classified article | `event_type` (30-value taxonomy), `impact_score` 0–1, `catalyst_score` 0–10, `sentiment_score` −1…1, `confidence` 0–1, `summary` |
| `stock_events` | Link between an event and a stock | `relevance_score` (1.0 keyword match, 0.6 LLM-only), `direction` (bullish/bearish/neutral) |

### Signals

**`signals`** — one row per scoring of one stock.

| Column | Notes |
|---|---|
| `timestamp`, `timeframe` | When scored, and the bar size (`1d`, `30m`, `1h`, …). Queries default to `1d` |
| `direction` | `bullish`, `bearish`, `watch`, `no_signal` |
| `score`, `confidence` | 0–100 composite score; confidence of the strategy that fired |
| `catalyst_score` … `risk_score` | The seven components, 0–100 each |
| `explanation` | JSON copy of the components |
| `status` | `active` (other states reserved) |

Rows are appended, never updated, so the table is a history. "Latest signal
per stock" is computed in SQL (`signals/queries.py`): the maximum timestamp
per stock for the timeframe, joined back to the rows.

**`trade_setups`** — for bullish/bearish signals: `entry_low`, `entry_high`,
`stop_loss`, `target_1`, `target_2`, `risk_reward`.

### History

**`historical_events`** — past news events with their realised outcome:
`event_type`, `event_timestamp`, `direction`, `regime` (market regime at the
time), `price_before`, and prices 15 minutes, 1 hour, 1 day and 5 days after
(the intraday ones are usually empty — only daily bars are used).

### User data

| Table | Purpose |
|---|---|
| `watchlists`, `watchlist_items` | Named lists; a stock appears at most once per list |
| `alerts` | `name`, optional `stock_id` (null = whole universe), `condition` (JSON), `is_active`, `triggered_at` |
| `alert_triggers` | One row per alert × stock × evaluation that matched, with the `signal_id` and a snapshot of `matched_values` |

### The handbook

| Table | Purpose |
|---|---|
| `doc_chapters` | One row per chapter of `docs/book.yaml`: `path`, `part`, `part_number`, `number`, `title`, full markdown `content`, `content_sha256`, `updated_at` |
| `doc_sections` | One row per `## ` section of a chapter (position 0 is the text before the first one): `chapter_id`, `position`, `anchor` (the heading id the Docs page links to), `title`, `content` |

These are a copy of `docs/`; the markdown files stay the source of truth and
the Docs page still reads the files.

The table definitions are in `db/sql/handbook.sql`: `CREATE TABLE` and
`CREATE INDEX` statements only (no data), all `IF NOT EXISTS`, and no schema
name, so they land in the first schema of the `search_path`.
`scripts/migrate_docs.py` runs that file with the search path set to
`DB_SCHEMA`, then loads the docs:

```bash
python scripts/migrate_docs.py                # create the tables if missing, then load docs/
python scripts/migrate_docs.py --tables-only  # tables only
python scripts/migrate_docs.py --write-sql    # regenerate handbook.sql after changing db/models.py
```

Run it again after editing the docs: only chapters whose markdown changed are
rewritten, and chapters removed from `book.yaml` are deleted. To apply the SQL
by hand: `PGOPTIONS=-csearch_path=basic psql -d loony_trading -f db/sql/handbook.sql`.

`alembic upgrade head` creates the same tables (migration `b3d1e7c2a9f4`) and
skips them if the script already did; either route works.

```sql
-- Which chapters mention the kill switch, and in which section?
SELECT c.number, c.title, s.title AS section
FROM doc_sections s JOIN doc_chapters c ON c.id = s.chapter_id
WHERE s.content ILIKE '%kill switch%' ORDER BY c.number, s.position;
```

## Migrations

Schema changes are Alembic migrations in `alembic/versions/`:

| Revision | Change |
|---|---|
| `ac63b0775ec4` | Initial schema |
| `0d5ce5521cce` | `news_events.catalyst_score` |
| `4f13cf9a05a0` | `alert_triggers` table |
| `46fd98926afb` | `historical_events.direction` and related similarity fields |
| `a89ec2781941` | `signals.timeframe` |
| `b3d1e7c2a9f4` | `doc_chapters` and `doc_sections` (the handbook) |

```bash
alembic upgrade head                           # apply everything
alembic revision --autogenerate -m "describe"  # after changing db/models.py
alembic downgrade -1                           # undo the last migration
```

`alembic/env.py` imports `db.models` so autogenerate sees every table, and
uses the engine from `db/base.py`, so it follows the same connection settings
and `DB_SCHEMA`.

## Maintenance

- `signals` and `alert_triggers` grow with every scheduled run (every 5
  minutes in market hours across 91 stocks ≈ 6,800 signal rows a day). Prune
  old rows periodically if disk matters, e.g.
  `DELETE FROM signals WHERE timestamp < now() - interval '90 days'` (delete
  their `trade_setups` and referencing `alert_triggers` first).
- Back up with `pg_dump loony_trading` (add `-n basic` when using `DB_SCHEMA=basic`).
