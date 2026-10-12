# Copilot

The Market Copilot (`/copilot`, `pages/Copilot.tsx`) answers plain-English
questions about the market using **only** data in the MarketPulse database.
It needs the database; with `LLM_PROVIDER=anthropic` and an
`ANTHROPIC_API_KEY` it writes answers with Claude, otherwise it runs in demo
mode.

## Asking questions

Type a question or click one of the examples:

- *Why is Reliance moving?*
- *Which stocks have unusual volume today?*
- *Show bullish stocks* / *Show bearish setups*
- *What are the latest market-moving events?*

Each answer shows the text, a **confidence** (low / medium / high) and the
**Evidence** it drew on — headlines with links, signal scores, analogue counts.
When the data does not support an answer, it says so ("insufficient evidence")
instead of guessing.

## What it can answer

The Copilot does not let the model roam free. A small keyword router decides
what kind of question it is, the matching data is pulled straight from the
database, and only then is the model asked to phrase an answer from that data:

| Question shape | Detected by | Data retrieved |
|---|---|---|
| Why is *stock* moving? | "why" + a stock name or ticker | The full [Why is it moving?](chart.md#why-is-it-moving) explanation |
| Unusual volume | "volume" + unusual / spike / high / surge | Latest signals with volume score ≥ 75 (top 10) |
| Bullish / bearish / watch signals | "bullish", "bearish", "watch … signal" | Latest signals in that direction, top 10 by score |
| Historical analogues | "histor", "similar event", "analog" | Win rate and median return of past events of the same type |
| Recent news | "news", "event", "happened", "moving today" | The 10 most recent classified events |
| Anything naming a stock | a stock name or ticker | Treated as "why is it moving" |

Anything else gets a fixed reply listing what it can answer — no model call is
made, because there is nothing to ground an answer in. Stock names are matched
deterministically against the universe (tickers in capitals, company names in
any case).

## Demo mode

Without a real LLM provider, the demo provider fills the answer schema with
placeholder text prefixed `[DEMO]`. Retrieval still runs for real, so the
evidence list is genuine; only the prose is a placeholder.

`POST /api/copilot/query` with `{"question": "..."}` is the API behind the
page. Internals: [Why and the Copilot](../marketpulse/why-and-copilot.md).
