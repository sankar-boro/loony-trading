# The Trading Playbook

A practical guide to using this project well: how the system thinks, how to run it day
to day, and how to build a disciplined process around it. This is not a promise of
profit — see the [disclaimer](#z-disclaimer-read-this) at the end, which you should
actually read.

**Who this is for:** you're running MarketPulse AI locally, in paper-trading mode,
against Indian equities (NSE), and you want to use it as a real research and
decision-support tool rather than just clicking around the dashboard.

---

## Contents

- [A. Setup](#a-setup)
- [B. The Mental Model — How the System Thinks](#b-the-mental-model--how-the-system-thinks)
- [C. The Composite Score, Precisely](#c-the-composite-score-precisely)
- [D. Daily Workflow](#d-daily-workflow)
- [E. Reading a Signal End to End (Worked Example)](#e-reading-a-signal-end-to-end-worked-example)
- [F. Building a Repeatable Edge](#f-building-a-repeatable-edge)
- [G. Risk Management, Concretely](#g-risk-management-concretely)
- [H. Watchlists & Alerts — Codifying Your Rules](#h-watchlists--alerts--codifying-your-rules)
- [I. Backtesting Before You Trust an Idea](#i-backtesting-before-you-trust-an-idea)
- [J. Weekly / Periodic Maintenance](#j-weekly--periodic-maintenance)
- [K. Tuning the System](#k-tuning-the-system)
- [L. Automating It (Scheduler)](#l-automating-it-scheduler)
- [M. Common Pitfalls](#m-common-pitfalls)
- [N. Glossary](#n-glossary)
- [Z. Disclaimer (read this)](#z-disclaimer-read-this)

---

## A. Setup

Full detail is in [Installation](../getting-started/installation.md); this is the short version so
this playbook stands alone.

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

| Key | Required? | What happens if it's missing |
|---|---|---|
| `UPSTOX_API_KEY` / `UPSTOX_API_SECRET` / `UPSTOX_ACCESS_TOKEN` | No | Falls back to **demo mode** — synthetic-but-realistic price data (§B) |
| `ANTHROPIC_API_KEY` | No | Falls back to a schema-correct offline LLM stub for classification/copilot |
| `NEWS_API_KEY` | No | Falls back to a small set of labeled `[DEMO DATA]` news items |

You can genuinely run the entire thing — dashboard, signals, backtests, alerts — with
zero API keys. Nothing will look real, but every page works and every code path is
exercised the same way it would be with live data. This matters: it means you can
learn the tool's behavior risk-free before pointing it at a real account.

```bash
python3 scripts/backfill_stocks.py          # populate the stock universe
python3 scripts/run_signal_engine.py        # score it once (needs price data → live or demo)
python3 scripts/seed_demo_data.py           # OR: one-shot full demo dataset (fresh DB only)
bash dashboard/start.sh                     # → http://localhost:5163
```

If `/api/status` reports `demo_mode: true`, you'll see an amber **DEMO DATA** banner
across the top of the dashboard. That's not a bug — it's the system refusing to let
synthetic data pass as real, per its own design principle (§B).

---

## B. The Mental Model — How the System Thinks

Before using any of the numbers this app shows you, it helps to know what it will
and won't do, because that shapes how much weight to put on any single output.

**1. Deterministic-first.** The LLM is used *only* for classification (what kind of
news event is this?) and composition (write a one-paragraph explanation). It is never
used for arithmetic, filtering, or routing. Every score, threshold comparison, and
trade-setup calculation is plain code you can read in `signals/composite.py`. This
means scores are reproducible — the same inputs always produce the same score, and
you can inspect exactly why a number is what it is.

**2. Evidence-grounded, not generative.** The "Why is it moving?" panel and the
Copilot don't free-associate. They retrieve real rows (signals, news, historical
events) *first*, and only compose an answer from what was retrieved. If there's
nothing to retrieve, you get "insufficient evidence" instead of a plausible-sounding
guess. This is the single most important thing to internalize: **a confident-sounding
answer is not the same as a well-evidenced one, and this system is built to prefer
saying nothing over inventing something.**

**3. Historical analogues are frequency statistics, not predictions.** When you see
"similar earnings moves: win rate 64%, median +1.4%," that's literally "of the past N
similar events in this database, this fraction moved up." It says nothing about
*this* specific situation, and it's explicitly labeled as historical analysis
everywhere it appears, never as a forecast.

**4. Demo data is always labeled.** Anything synthetic — price bars generated
because no Upstox token is configured, canned news items, seeded historical events —
carries an explicit marker (`DEMO DATA` banner, `[DEMO]` prefix in text, a `demo_mode`
API flag) so you can never mistake it for a live market read.

**5. Research is separate from trading.** MarketPulse (scores, alerts, Copilot) never
places an order. Orders come only from the trading bot — simulated in paper mode,
real when you run `python main.py --mode live`. Positions and Trades show whichever
bot ran last; check which one before reading them.

---

## C. The Composite Score, Precisely

Every stock's Signals-page score (0–100) is a weighted blend of seven components,
defined in `config/settings.yaml → signal_engine.weights`:

| Component | Weight | What it measures |
|---|---|---|
| Catalyst | 25% | The stock's most material news in the last 3 days: classifier catalyst score × relevance |
| Technical | 20% | Confidence of the best firing strategy (the same strategies the bot trades) |
| Momentum | 15% | How far RSI(14) is from 50, in either direction |
| Volume | 15% | Latest volume vs. its 20-bar average — 50 is average, 100 is double |
| Historical | 10% | 1-day win rate of past events of the same type and direction (≥ 5 samples, else 50) |
| Regime | 10% | Whether the market regime suits the signal's direction |
| Risk | 5% | Calmer stocks score higher (ATR as a % of price) |

The exact formulas are in [Composite Signals](../marketpulse/composite-signals.md).

**How direction is decided** (`signals/composite.py::_classify`):

```
score ≥ 70 AND confidence ≥ 65   →  BULLISH or BEARISH (direction from the dominant strategy)
score ≥ 50 (but below the above) →  WATCH
otherwise                         →  NO_SIGNAL
```

Those thresholds (`quality_gate.min_score`, `min_confidence`, `watch_score`) are
config, not hardcoded — see [§K](#k-tuning-the-system) if you want them stricter or
looser. A **WATCH** signal means "interesting, not yet confirmed" — treat it as a
prompt to look closer, not a trade trigger.

When a signal is BULLISH or BEARISH, a trade setup is attached: entry zone, stop-loss,
target, and risk/reward ratio, computed from ATR and the triggering strategy's own
levels — visible in the Signals page breakdown panel.

---

## D. Daily Workflow

This is the routine worth building as a habit. Each step names the page to use.

### Pre-market (before 09:15 IST)

1. **News** — scan overnight headlines, filtered by event type if you have a
   watchlist sector in mind. Look for earnings, guidance, or regulatory items with a
   high impact score.
2. **Alerts → history** — check what fired overnight/pre-market on your standing
   rules.
3. **Copilot** — ask `"What news happened today?"` or `"What's bullish right now?"`
   for a fast synthesis instead of reading every headline yourself.

### At the open

4. **Dashboard** — index ticker + KPI row for the broad tape; Live Signals feed for
   anything freshly triggered.
5. **Signals**, filtered to **Bullish** / **Bearish** — this is your ranked shortlist
   for the session. Click into anything scoring high with confidence to see the
   component breakdown.
6. **Chart → "Why is it moving?"** for any name you're seriously considering — cross-
   check the composite score against the actual driver ranking and recent news.

### Before adding any position

7. **Portfolio Risk** — check sector exposure and correlation *before* you add
   anything, not after. If the sector you're about to add to is already flagged, that's
   information, not just a warning to dismiss.

### Mid-day

8. **Positions** — monitor open paper trades; the stop/target progress bar tells you
   at a glance how close price is to either exit.
9. Groom your **Watchlists** as ideas develop — separate "watching" from "committed."

### End of day

10. **Daily P&L** — log the day. Look at win rate and Sharpe trend over time, not any
    single day's number.
11. **Strategies** — check which strategies are actually contributing P&L this week
    vs. just carrying weight in the ensemble.

---

## E. Reading a Signal End to End (Worked Example)

Say **INFY** shows up on the Signals page at score 82, confidence 74, BULLISH.

1. **Open the breakdown panel** (click the row). You see the seven components — say
   catalyst=88, technical=70, momentum=65, volume=90, historical=71, regime=60,
   risk=55. Volume and catalyst are doing the heavy lifting here — that's a specific,
   checkable claim, not just "the AI likes it."
2. **Go to Chart → Why is it moving?** for INFY. It should independently point at the
   same catalyst — if the panel cites a contract-win headline and the breakdown's top
   component is catalyst, that's corroboration, not coincidence (they share the same
   underlying data, but seeing it from two angles catches copy/scoring bugs and gives
   you the actual headline to judge for yourself).
3. **Check the historical analogue.** "Contract-win events, 40 samples, 1-day win rate
   58%, median +0.9%." That's a mildly favorable base rate, not a lock — treat the
   score's 10% historical weight the same way.
4. **Check the trade setup**: entry zone, stop-loss, target, risk/reward. Does the
   risk/reward clear your own personal minimum (many traders use 1.5–2.0)? If not, a
   high score doesn't fix a bad risk/reward.
5. **Check Portfolio Risk** before sizing: does adding INFY push IT-sector exposure
   or correlation with an existing position over the warning threshold?
6. **Decide** — and if you take it, note *why* somewhere (even a scratch text file).
   The Trades page will tell you your win rate later; only your own notes will tell
   you whether you're actually following your process or just reacting to scores.

---

## F. Building a Repeatable Edge

The honest version of "how to be profitable" with a tool like this is: **the tool
doesn't have an edge by itself — your process for using it consistently does.**
Concretely:

- **Triangulate, don't single-source.** Composite score, historical analogue, and
  news catalyst are three independent-ish views (§E). A signal that's strong on all
  three is a materially different situation than one that's strong on volume alone.
- **Use WATCH as a queue, not a dead end.** Set an alert on the exact condition that
  would promote a WATCH stock to something you'd act on, instead of manually
  rechecking it.
- **Let backtests set your expectations, not your enthusiasm.** Before trusting a
  strategy or a condition rule, backtest it with walk-forward validation (§I) — a
  strategy that only worked on the window you eyeballed is not a strategy, it's
  hindsight.
- **Size by risk, not by conviction.** The Portfolio Risk page's max-loss figure (sum
  of stop-distance × size across positions) is the number that matters when you're
  wrong, not the number that matters when you're right. Check it *before* the trade.
- **Keep a real trading journal**, even in paper mode. The Daily P&L and Trades pages
  give you the *what*; only your own notes give you the *why*, which is what you
  actually improve over time.
- **Review, don't just accumulate.** Weekly, look at Strategies' performance section
  — a strategy with a negative Sharpe over your actual paper-trading window shouldn't
  keep its ensemble weight just because a two-year backtest once liked it.

---

## G. Risk Management, Concretely

The Portfolio Risk page (`/risk`) exists to make risk visible before it's a problem.
Its thresholds:

| Metric | Default threshold | What crossing it means |
|---|---|---|
| Sector concentration | 35% of capital | One sector could sink the whole book on one piece of news |
| Pairwise correlation | ≥ 0.70 | Two "different" positions that will likely move together — not real diversification |
| Total exposure | 20% of capital (`max_portfolio_risk`) | You're more leveraged into the market than your own risk budget allows |
| Daily loss | 5% of capital (`max_daily_drawdown`) | The point at which the system would block new trades in live/paper execution |

The page only **warns**. What the trading bots actually enforce is narrower — know
the difference:

- The **daily loss** limit is enforced: the risk manager stops opening trades once
  the day's realised loss passes `max_daily_drawdown`.
- `max_portfolio_risk` is enforced **per position** (no single position may exceed
  20 % of capital), not as a total-exposure cap — the page's "total exposure"
  warning is stricter than the bot.
- **Correlation** is enforced only by the live bot (`main.py`, at
  `portfolio.correlation_limit`), not by the paper trader.
- **Sector concentration** is not enforced by either bot.

See [Risk Management](../engine/risk-management.md) for exactly what each component does.

**Max loss**, shown on the same page, is the sum of `(entry − stop) × size` across
every open position — literally "what happens if every stop I've set gets hit today."
It's the single most useful number on that page for a pre-mortem gut check.

---

## H. Watchlists & Alerts — Codifying Your Rules

Watchlists are just organization — as many named lists as you want. Alerts are where
process discipline actually gets encoded.

**Alert condition DSL** — `<field>__<operator>: <value>`, combined with AND:

| Fields | Operators |
|---|---|
| `score`, `confidence`, `catalyst_score`, `technical_score`, `momentum_score`, `volume_score`, `historical_score`, `regime_score`, `risk_score`, `direction` | `gt`, `gte`, `lt`, `lte`, `eq` |

Examples worth setting up:

```text
score__gt: 80, volume_score__gte: 75        → high-conviction + unusual volume
direction__eq: "bullish", confidence__gte: 70   → clean bullish confirmation
catalyst_score__gt: 85                       → big news-driven mover, any direction
```

Leave `symbol` blank to scan the whole universe; scope it to one stock for a
position-specific watch (e.g., "alert me if my existing HDFCBANK position's signal
flips bearish"). Every trigger is logged with the exact values that matched — that
history is worth reviewing periodically to see whether your rule is actually
selective or just firing on everything.

**Why this matters for discipline:** an alert rule is a decision you made once, calmly,
ahead of time. Manually re-scanning the Signals page in the middle of a session is a
decision you make repeatedly, under whatever mood you're in that moment. Prefer the
former for anything you can specify as a condition.

---

## I. Backtesting Before You Trust an Idea

The Strategy Lab (`/backtest`) is where "I think this works" becomes "here's the
evidence." Three things to always turn on, not just the base run:

1. **Walk-forward** — splits history into out-of-sample chunks. Look at the per-split
   table, not just the final metrics. A strategy with a great overall Sharpe but wildly
   inconsistent per-split results is telling you it got lucky in aggregate, not that
   it's robust.
2. **Monte Carlo** — 500 resampled simulations of your trade sequence, giving a
   Sharpe/drawdown *range* (5th–95th percentile) instead of one realized path. If the
   5th-percentile Sharpe is negative, your single backtest result was closer to the
   lucky end of the distribution than you'd want to bet real capital on.
3. **Benchmark vs. Nifty** — a positive return that trails the index isn't really an
   edge; it's beta. Alpha (the benchmark-adjusted return) is the number that actually
   argues for active strategy selection over just holding the index.

The engine is look-ahead-bias safe by construction — a decision at bar *i* only ever
sees `df[:i]`, verified by a dedicated regression test (`tests/test_backtest_lookahead.py`)
that checks removing future bars never changes a trade that already closed. You don't
need to worry about the backtest silently cheating; you do still need to worry about
*overfitting your own strategy selection* to what looks good in one specific backtest.

---

## J. Weekly / Periodic Maintenance

- **Review triggered alerts** — prune rules that fire too often (not selective) or
  never (too strict / wrong threshold).
- **Re-run backtests** on strategies you're actively weighting, on a rolling recent
  window, not just the original tuning window.
- **Check `Strategies` performance** against the ensemble weights in
  `config/settings.yaml` — a strategy earning its weight vs. one that's dead weight.
- **Historical event backfill** — if running the scheduler (§L), this happens nightly
  automatically; otherwise run `python3 scripts/backfill_historical_events.py`
  periodically so the historical-analogue component keeps improving with real,
  matured outcomes instead of staying thin.

---

## K. Tuning the System

Everything below lives in `config/settings.yaml` — no code changes needed.

**Make signals stricter or looser:**
```yaml
signal_engine:
  quality_gate:
    min_score: 70        # raise for fewer, higher-conviction BULLISH/BEARISH calls
    min_confidence: 65
    watch_score: 50       # raise to shrink the WATCH band
```

**Reweight what drives the composite score** (must sum to 1.0):
```yaml
signal_engine:
  weights:
    catalyst: 0.25    # more weight → more news-reactive
    technical: 0.20
    momentum: 0.15
    volume: 0.15
    historical: 0.10  # more weight → more influenced by base-rate outcomes
    regime: 0.10
    risk: 0.05
```

**Tighten risk defaults:**
```yaml
risk:
  max_risk_per_trade: 0.01     # 1% of capital per trade
  max_daily_drawdown: 0.05     # 5% daily loss limit
  max_portfolio_risk: 0.20     # 20% total exposure cap
```
These same numbers drive the Portfolio Risk page's warnings (§G) and the risk
manager — though, as §G explains, the two apply them differently.

**Add a stock to the tracked universe** — edit `config/instruments.py`'s
`STOCK_UNIVERSE` dict with its ISIN, sector, and market cap tier, then
`python3 scripts/backfill_stocks.py`.

**Retune strategy ensemble weights** from real backtest results:
`python3 scripts/tune_weights.py --dry-run` to preview, then without `--dry-run` to
write `strategies.enabled` and `strategies.weights` into `settings.yaml` (strategies it
cannot backtest keep their current settings).

---

## L. Automating It (Scheduler)

By default, nothing runs on its own — you trigger news ingestion, signal scoring, and
alert evaluation manually (via the API or CLI scripts). To automate:

```yaml
scheduler:
  enabled: true                     # off by default, on purpose
  news_interval_seconds: 60
  signal_interval_seconds: 300      # every 5 min — tune to your broker API's rate limits
  alert_interval_seconds: 300
  market_hours_only: true           # signals/alerts pause when NSE is closed; news doesn't
  historical_backfill_hour: 18      # IST, once daily after close
```

It also retrains the ML model every Sunday (kept only if it beats the baselines). Check
`GET /api/scheduler/status` — or the Intraday Lab page — for next-run times and the last
outcome of each job. See [The Scheduler](../marketpulse/scheduler.md). It's intentionally off by default — turning it on means the app starts hitting
your configured broker/news APIs on a real cadence, so do it deliberately, not as a
side effect of starting the dashboard.

---

## M. Common Pitfalls

- **Trusting a single backtest run.** Always check walk-forward and Monte Carlo (§I)
  before believing an overall-window result.
- **Ignoring correlation/sector warnings because each position "looks fine" alone.**
  Concentration risk is a portfolio property, not a per-position one — that's exactly
  what the Portfolio Risk page exists to catch.
- **Treating historical analogue win rates as odds you can bet at face value.** They're
  a base rate over past similar events, explicitly not a probability for this specific
  trade — the UI labels them that way for a reason.
- **Mistaking demo data for live data.** If you see the amber DEMO DATA banner,
  nothing on screen is real market information, however realistic it looks.
- **Manually re-deciding the same rule every session** instead of encoding it as an
  Alert. If you find yourself checking the same condition daily, that's a sign to
  automate the check, not the decision.
- **Chasing WATCH-tier signals like they're confirmed.** They cleared the lower bar
  on purpose — that's the point of having two tiers.
- **Skipping the risk check because a signal "looks too good to pass up."** The
  signals that feel most compelling are exactly the ones worth a deliberate pause.

---

## N. Glossary

| Term | Meaning |
|---|---|
| **Composite score** | 0–100 blended score across catalyst/technical/momentum/volume/historical/regime/risk |
| **Confidence** | 0–100 — the confidence of the strategy that fired, × 100 |
| **Direction** | `bullish` / `bearish` / `watch` / `no_signal` |
| **Catalyst** | A classified news event with impact and sentiment scores |
| **Historical analogue** | Aggregated outcome stats for past similar events (win rate, median return) |
| **Regime** | Market condition classification (trending / ranging / volatile) used to weight strategies |
| **Trade setup** | Entry zone, stop-loss, target, risk/reward attached to an actionable (bullish/bearish) signal |
| **Demo mode** | No live broker token configured — all price/signal data is clearly-labeled synthetic |
| **Walk-forward** | Backtesting technique that validates on out-of-sample chunks, not just one fitted window |
| **Max loss** | Sum of `(entry − stop) × size` across open positions — total capital at risk if every stop hits |

---

## Z. Disclaimer (read this)

This is a **paper-trading and research tool**. Nothing it shows — scores,
explanations, historical analogues, or Copilot answers — is investment advice, a
recommendation, or a guarantee of future performance. Historical win rates describe
the past; they do not predict the future. Backtest results (even walk-forward and
Monte Carlo ones) describe a model's behavior on historical data, not a promise about
live markets, which are non-stationary and can invalidate any strategy without
warning.

"Being profitable" with this tool, to the extent it's possible at all, comes from the
process — triangulating evidence, sizing by risk instead of conviction, backtesting
honestly, and reviewing your own results — not from any single number the dashboard
shows you. Treat every score as an input to your own judgment, never a substitute for
it.
