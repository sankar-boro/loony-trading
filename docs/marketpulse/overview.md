# MarketPulse AI Overview

MarketPulse AI is the research layer of Loony Trading. It reads the news,
scores every stock in the universe, explains why stocks move, watches your
alert rules and answers questions — and stores all of it in PostgreSQL so the
dashboard can show it. It never places orders; the trading bot does not read
its output.

## Design principles

The code follows a few rules consistently; knowing them explains many design
choices you will meet in the following chapters.

| Principle | In practice |
|---|---|
| **Deterministic first, LLM last** | Stock matching, scoring, alert evaluation and question routing are plain code. An LLM is only used to classify articles and to phrase Copilot answers from retrieved data |
| **Validated LLM output** | Every LLM call returns a Pydantic schema (`ai/schemas.py`), never free text |
| **Evidence, not prediction** | Historical analogues are labelled "historical analysis — not a prediction"; the Copilot answers only from retrieved rows and says "insufficient evidence" otherwise |
| **Quality over volume** | The composite engine's gate makes most stocks *No signal* on most days |
| **Works offline** | Without keys it runs on demo prices, demo news and a demo LLM — every synthetic item is labelled |
| **Partial failure is fine** | One symbol failing to fetch or score is logged and skipped, never aborting a run |

## Data flow

```
 NewsAPI / demo news
        │  every 60 s (scheduler) or "Fetch latest news"
        ▼
 News pipeline ──► news_articles, news_events, stock_events
        │                                   │
        │ (7+ days later)                   │ catalyst (last 3 days)
        ▼                                   ▼
 Historical backfill ──► historical_events ──► Composite signal engine ◄── candles (Upstox / demo)
                                │                     │  every 5 min in market hours
                                │                     ▼
                                │                  signals, trade_setups
                                │                     │
                                ▼                     ▼
                  "Why is it moving?"  ◄──────  Alert evaluation ──► alert_triggers ──► Telegram
                         │                            ▲
                         ▼                            │
                      Copilot                    alerts (your rules)
```

## Components

| Component | Code | Chapter |
|---|---|---|
| Persistence | `db/base.py`, `db/models.py`, `alembic/` | [The Database](database.md) |
| News ingestion | `data_engine/news/` | [The News Pipeline](news-pipeline.md) |
| LLM abstraction | `ai/client.py`, `ai/schemas.py` | [The News Pipeline](news-pipeline.md#the-llm-layer) |
| Composite scoring | `signals/composite.py`, `scripts/run_signal_engine.py` | [Composite Signals](composite-signals.md) |
| Historical analogues | `signals/historical.py`, `scripts/backfill_historical_events.py` | [Historical Analogues](historical-analogues.md) |
| Explanations and Copilot | `signals/why.py`, `signals/copilot.py` | [Why and the Copilot](why-and-copilot.md) |
| Alerts | `signals/alerts.py` | [Alert Evaluation](watchlists-alerts.md) |
| Scheduling | `scheduler/` | [The Scheduler](scheduler.md) |

## Getting it running

```bash
docker compose up -d db                 # PostgreSQL
alembic upgrade head                    # schema
python scripts/backfill_stocks.py       # the 91-stock universe → stocks table
python scripts/run_signal_engine.py     # score every stock once
```

…or `python scripts/seed_demo_data.py` for a fully offline demo. Then set
`scheduler.enabled: true` in `config/settings.yaml` and restart the dashboard
backend to keep everything refreshed automatically.
