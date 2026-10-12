# Why and the Copilot

Two features turn stored data into explanations: **Why is it moving?**
(`signals/why.py`) and the **Copilot** (`signals/copilot.py`), which reuses
it. Both follow the same rule: every statement must trace back to a database
row; when there is nothing to point at, say so.

## Why is it moving?

`explain_move(db, symbol)` returns `None` for an unknown symbol (the API turns
that into 404) and otherwise gathers:

1. **The latest composite signal** for the stock, any timeframe.
2. **Recent news** — up to 10 stock–event links from the last 7 days, newest
   first, with headline, source, URL, event type, sentiment, impact and
   summary.
3. **Drivers** — the signal's components ranked by contribution
   (component × weight), keeping only positive components. The weights here are
   the default composite weights (catalyst 0.25 … risk 0.05).
4. **A historical analogue** — for the most recent news item's event type and
   direction, the 1-day result from the [analogue engine](historical-analogues.md),
   included when it has at least one sample.
5. **A conclusion** sentence:
   - nothing found → "No scored signal or recent news found … Insufficient evidence."
   - a driver exists → "The move appears primarily driven by *top driver*
     (contributing *x* of the *score* composite score)." plus, with ≥ 5
     analogue samples, how often similar events closed higher the next day;
   - news but no signal → "News found … but no composite signal has been scored yet."

Response (`GET /api/stocks/{symbol}/why`):

```json
{ "symbol": "TCS",
  "signal": { "direction": "watch", "score": 58.4, "confidence": 62.0, "timestamp": "…" },
  "drivers": [ { "factor": "catalyst", "label": "News catalyst", "score": 80.0,
                 "weight": 0.25, "contribution": 20.0 }, … ],
  "recent_news": [ … ],
  "historical_analogue": { "event_type": "contract_win", "direction": "bullish",
                           "sample_count": 12, "win_rate_pct": 66.7, "median_return_pct": 0.84,
                           "label": "Historical analysis of past events — not a prediction" },
  "conclusion": "The move appears primarily driven by news catalyst (contributing 20.0 of the 58.4 composite score)." }
```

## The Copilot

`answer_query(db, question)` works in three steps.

### 1. Route the question (no LLM)

`_parse_intent()` checks the lower-cased question for keywords, in this order,
and resolves stock names with the same matcher as the news pipeline:

| Order | Condition | Intent |
|---|---|---|
| 1 | "why" and a stock | `why_moving` |
| 2 | "volume" and unusual/spike/high/surge | `unusual_volume` |
| 3 | "bullish" | signals filtered to bullish |
| 4 | "bearish" | signals filtered to bearish |
| 5 | "watch" and "signal" | signals filtered to watch |
| 6 | "histor", "similar event", "analog" | `historical_analogue` |
| 7 | "news", "event", "happened", "moving today" | `news_recent` |
| 8 | any stock named | `why_moving` |
| — | none of the above | `unsupported` |

Unsupported questions get a fixed list of what the Copilot can answer — no LLM
call.

### 2. Retrieve data (no LLM)

| Intent | Retrieved |
|---|---|
| `why_moving` | `explain_move()` output |
| `unusual_volume` | Latest daily signals with volume score ≥ 75, top 10 |
| signals filter | Latest daily signals in the direction, top 10 by score |
| `news_recent` | 10 newest classified events |
| `historical_analogue` | Analogue stats for the event type of the stock's latest news |

Nothing retrieved → "No matching data found in the database for this
question." with `insufficient_evidence: true`.

### 3. Phrase the answer (LLM)

The retrieved JSON — and only that — goes to the LLM with a system prompt that
forbids outside knowledge, invented numbers and price predictions, and asks it
to set `insufficient_evidence` when the data does not answer the question. The
validated `CopilotAnswer` has `answer`, `confidence` (low/medium/high),
`evidence` and `insufficient_evidence`. If the model returns no evidence list,
the retrieval step's own evidence lines are used.

## Extending the Copilot

To support a new question shape: add a branch to `_parse_intent()`, a matching
retrieval in `_retrieve()` that returns `(data, evidence)`, and mention it in
`_UNSUPPORTED_ANSWER`. Keep retrieval deterministic — the LLM should only ever
describe data you hand it.
