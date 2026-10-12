# Watchlists and Alerts

Two database-backed pages for codifying what you care about: **Watchlists**
(named lists of stocks) and **Alerts** (rules evaluated against every stock's
composite signal).

## Watchlists

`/watchlists`, `pages/Watchlists.tsx`.

- Create a list with the **New watchlist…** box; delete it from its row.
- Select a list, then add symbols with **Add symbol, e.g. RELIANCE…**; remove
  them from the list. Adding a symbol twice is ignored. Symbols must exist in
  the `stocks` table (`python scripts/backfill_stocks.py` loads the universe).

| Action | Endpoint |
|---|---|
| List | `GET /api/watchlists` |
| Create | `POST /api/watchlists` `{"name": "Banks"}` |
| Delete | `DELETE /api/watchlists/{id}` |
| Add symbol | `POST /api/watchlists/{id}/items` `{"symbol": "HDFCBANK"}` |
| Remove symbol | `DELETE /api/watchlists/{id}/items/{symbol}` |

These are separate from the fixed 30-stock watchlist on the Home page
(`GET /api/watchlist`, singular), which is a read-only live-price panel.

## Alerts

`/alerts`, `pages/Alerts.tsx`, refreshing every 30 s.

### Creating an alert

| Field | Meaning |
|---|---|
| Name | Anything descriptive |
| Symbol | One stock, or blank for the whole universe |
| Conditions | One or more rows of *field — operator — value*; **all** must hold |

Fields: `score`, `confidence`, `catalyst_score`, `technical_score`,
`momentum_score`, `volume_score`, `historical_score`, `regime_score`,
`risk_score` (all 0–100). Operators: `>`, `≥`, `<`, `≤`, `=`. Through the API
you can also test `direction` (e.g. `"direction__eq": "bullish"`).

Under the hood a condition is a flat JSON object of `<field>__<op>` keys:

```json
{ "name": "Strong bullish with volume",
  "symbol": null,
  "condition": { "score__gte": 75, "volume_score__gt": 70, "direction__eq": "bullish" } }
```

The server rejects unknown fields and operators (`400`), and unknown symbols
(`404`).

### Managing alerts

- **Pause / resume** with the toggle (`PATCH /api/alerts/{id}?is_active=false`).
- **Delete** (`DELETE /api/alerts/{id}`).
- Each alert shows when it last triggered and, expanded, its last 10 triggers:
  the stock, the matched values and the time (`GET /api/alerts/{id}/triggers`).

### When alerts fire

Alerts are checked against the **latest daily signal of each stock**:

- automatically every 5 minutes during market hours when the
  [scheduler](../marketpulse/scheduler.md) is enabled, right after signals are
  re-scored;
- on demand with **Evaluate now** (`POST /api/alerts/evaluate`);
- against intraday signals from the [Intraday Lab](intraday-lab.md)
  (`POST /api/alerts/evaluate?timeframe=30m`).

Every match is stored as a trigger row and, if Telegram is configured, sent as
one message listing up to ten triggers. An alert fires again on every
evaluation while its condition stays true — there is no built-in cooldown.

Evaluation logic: [Watchlists and Alerts internals](../marketpulse/watchlists-alerts.md).
