# News

The News Terminal (`/news`, `pages/News.tsx`) lists market news that the
MarketPulse pipeline has fetched, classified and linked to stocks. It needs the
database.

## The news feed

`GET /api/news` (refreshed every 30 s) returns the newest classified events
first (50 by default, up to 200 with `limit`). Each card shows:

| Element | Meaning |
|---|---|
| Headline | Links to the original article |
| Age | How long ago it was published |
| Summary | The classifier's one-paragraph summary |
| Event type badge | One of 30 categories — earnings, guidance, order win, regulatory action, brokerage upgrade, macro news, … |
| Sentiment badge | **Bullish** above +0.15, **Bearish** below −0.15, otherwise **Neutral** |
| "catalyst x/10" | The event's `impact_score` × 10 (see the note below) |
| Stock tags | Stocks the event was linked to |

> **Labelling note:** the card's "catalyst" figure is the 0–1 *impact score*
> scaled to 10, not the separate 0–10 `catalyst_score` that feeds the composite
> signal; the API does not return `catalyst_score`. Both are produced by the
> classifier and usually move together.

`sentiment_score` is the classifier's direction (+1 bullish, −1 bearish, 0
neutral) multiplied by its confidence, so it ranges −1 to +1 and a low-confidence
call stays near zero.

## Filters

- **Event type** — `All events` or one category (the list comes from
  `GET /api/news/event-types`).
- **Symbol** — only events linked to that stock.

## Fetch latest news

The **Fetch latest news** button calls `POST /api/news/ingest`, which runs one
pass of the ingestion pipeline (up to 20 articles) and refreshes the feed. With
`NEWS_API_KEY` set, articles come from NewsAPI.org (free tier: 100 requests a
day); without it, five canned demo articles are used, each labelled
`[DEMO DATA]`. Already-stored articles are skipped, so pressing it twice does
not duplicate anything.

When the [scheduler](../marketpulse/scheduler.md) is enabled, ingestion runs
automatically every 60 seconds and the button is only needed for an immediate
refresh.

How articles are fetched, deduplicated, matched to stocks and classified is
explained in [The News Pipeline](../marketpulse/news-pipeline.md).
