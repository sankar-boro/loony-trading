# The News Pipeline

`data_engine/news/` turns raw articles into structured, stock-linked events:

```
fetch ──► dedupe ──► match stocks (deterministic) ──► classify (LLM) ──► store
```

One pass is `NewsIngestionPipeline().run_once(db, limit=20)`, called by the
scheduler's `news_ingest` job, the dashboard's **Fetch latest news** button
(`POST /api/news/ingest`) and `scripts/seed_demo_data.py`. It returns counts:

```json
{ "fetched": 20, "ingested": 7, "skipped_duplicate": 13, "events_created": 7 }
```

## Providers

A provider is anything with `get_latest_news(limit) -> list[RawNewsItem]`
(`provider.py`), where a `RawNewsItem` has source, title, URL, published time,
content, author and language.

| Provider | Used when | Behaviour |
|---|---|---|
| `NewsAPIProvider` | `NEWS_API_KEY` is set to a real value | NewsAPI.org `/v2/everything` for `NSE OR BSE OR Nifty OR Sensex OR "Indian stocks"`, English, newest first, up to 100. Free tier: 100 requests/day, delayed articles. Errors are logged and return nothing |
| `DemoNewsProvider` | otherwise | Five canned stories (Reliance results, HDFC Bank CFO change, TCS contract win, RBI policy, Adani downgrade), timestamped minutes ago, each tagged `[DEMO DATA]` |

Placeholder values from `.env.example` such as `your_newsapi_key_here` count as
"not set", so a fresh checkout falls back to demo news instead of failing.

## Deduplication

Each article is hashed (SHA-256 of `source|title|url`). If the hash is already
in `news_articles`, the article is skipped. Re-running ingestion is therefore
always safe.

## Matching articles to stocks

`entity_resolution.resolve_stock_mentions(text)` finds stocks in the headline
and body without any LLM:

- **Tickers** are matched case-sensitively as whole words (`RELIANCE`, `TCS`).
  Case matters because several tickers are ordinary English words
  (`PERSISTENT`, `IDEA`, `RAIN`) — "persistent inflation" must not match
  Persistent Systems.
- **Company names** are matched case-insensitively as whole words, both the
  full name and the name without filler words (Ltd, Limited, India, Industries,
  Corporation, …). "Tata Consultancy Services" matches TCS. When two companies
  would share an alias, the first one in the universe keeps it.

## Classification

`NewsClassifier.classify()` sends the headline, the first 4,000 characters of
the body and the candidate stocks to the LLM with a system prompt that asks for
an evidence-based classification — not a price prediction — and receives a
validated `StructuredAnalysis`:

| Field | Range | Meaning |
|---|---|---|
| `summary` | text | What the article says |
| `event_type` | 30 slugs | earnings, revenue, profit_warning, guidance, management_change, ma, acquisition, partnership, contract_win, order_win, regulatory_approval, regulatory_action, government_policy, product_launch, litigation, debt, credit_rating, dividend, buyback, promoter_activity, insider_activity, fii_dii_activity, brokerage_upgrade, brokerage_downgrade, sector_news, macro_news, commodity_shock, currency_shock, geopolitical_event, other |
| `direction` | bullish / bearish / neutral | Likely direction for the affected stocks |
| `confidence` | 0–1 | How sure the classifier is |
| `catalyst_score` | 0–10 | Materiality, surprise, recency, source credibility |
| `impact_score` | 0–1 | Expected relevance |
| `time_horizon` | text | e.g. "intraday", "weeks" |
| `affected_stocks` | tickers | Candidates the article supports, plus any the keyword match missed |
| `evidence`, `risks`, `invalidating_conditions` | lists | Supporting reasoning |

An `event_type` outside the taxonomy (a near miss like "Earnings") is
normalised to the slug, or to `other`.

## What gets stored

For each new article:

1. A `news_articles` row.
2. A `news_events` row with the classification. `sentiment_score` is
   direction (+1 / −1 / 0) × confidence.
3. A `stock_events` row for every stock in *keyword matches ∪ LLM
   affected_stocks* that exists in the `stocks` table — relevance 1.0 for
   keyword matches, 0.6 for stocks only the LLM named — carrying the direction.

## The LLM layer

`ai/client.py` defines one interface, `complete_structured(system, prompt,
schema) -> schema instance`, with two implementations chosen by
`get_llm_provider()`:

| Provider | Selected when | Behaviour |
|---|---|---|
| `AnthropicProvider` | `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` set | Calls Claude with `client.messages.parse(..., output_format=Schema)`, `max_tokens=2048`; the SDK validates the response against the Pydantic schema |
| `DemoLLMProvider` | otherwise (default) | Fills any schema with placeholders: first value of a `Literal`, the midpoint of numeric ranges, empty lists, `[DEMO] …` strings |

The model is `ANTHROPIC_MODEL`, defaulting to `claude-opus-5` (`DEFAULT_MODEL`).
That is a valid model id, but Claude Opus 5.5 (`claude-opus-5-5`) is newer
and cheaper per token; set `ANTHROPIC_MODEL=claude-opus-5-5` to use it.

With the demo provider every article is classified as `other`, bullish, with
confidence 0.5 and catalyst 5 — fine for exercising the pipeline, meaningless
as analysis.

## Cost and rate limits

Each new article costs one LLM call; duplicates cost nothing. At the
scheduler's 60-second interval NewsAPI's free tier (100 requests/day) runs out
in under two hours — raise `scheduler.news_interval_seconds` (e.g. to 900) when
using the free tier.
