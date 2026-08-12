Absolutely. Below is a **single master prompt** you can paste into Claude Code. It is designed to make Claude behave like a senior product engineer/quant developer and **actually build the application**, rather than just give you an architecture document.

I’ve assumed **Indian equities (NSE/BSE)**, with intraday trading as the primary use case, and designed the system so the AI explains signals rather than pretending to predict the market.

# MASTER PROMPT — BUILD AN AI-POWERED INDIAN STOCK TRADING INTELLIGENCE PLATFORM

You are a senior staff-level full-stack engineer, quantitative developer, data engineer, ML engineer, product designer, and DevOps engineer.

Your job is to **design and build a production-quality MVP of an AI-powered Indian stock-market intelligence platform**.

The application is intended for traders who want to discover potentially actionable NSE/BSE stock opportunities by combining:

* Real-time/near-real-time market data
* Company announcements
* Financial results
* News
* Corporate actions
* Analyst actions
* FII/DII activity
* Bulk/block deals
* Technical indicators
* Price/volume behavior
* Historical reactions to similar events
* Quantitative scoring
* AI-generated explanations

The application must NOT pretend to know the future and must NOT blindly generate unsupported BUY/SELL recommendations.

Instead, it should produce **evidence-backed trading setups with transparent reasoning, confidence scores, risk information, entry/stop/target calculations, and supporting evidence.**

---

# 1. PRODUCT VISION

Build a web application called:

**MarketPulse AI**

Tagline:

**“Find the market-moving signals before they become obvious.”**

Primary market:

**India — NSE/BSE equities**

Primary use case:

**Intraday and short-term trading intelligence**

Secondary use cases:

* Swing trading
* Market research
* Stock discovery
* News analysis
* Technical analysis
* Event-driven trading research

The core question the application should answer is:

> “What is happening in the Indian stock market right now, which stocks are being affected, why are they moving, and is there a statistically interesting trading setup?”

---

# 2. IMPORTANT PRODUCT PRINCIPLE

Do NOT build a generic stock-news website.

Build a **decision-support and market-intelligence system**.

The product should transform:

NEWS + MARKET DATA + TECHNICAL DATA + FUNDAMENTAL DATA

into:

EVENT → IMPACT → STOCK → SIGNAL → SETUP → RISK → EVIDENCE

Example:

```text
RELIANCE

News:
Positive earnings surprise

Market:
Price +3.2%
Volume 2.1x 20-day average
Relative strength +1.8%

Technical:
Above VWAP
Above 20 EMA
Breakout confirmed

Historical analogues:
Similar earnings events produced
+2.4% median 1-day return

Signal:

BULLISH

Signal Score: 84/100
Catalyst Score: 9/10
Technical Score: 8/10
Volume Confirmation: 9/10
Historical Edge: 7/10

Potential Setup:
Entry: ₹X–₹Y
Stop: ₹X
Target 1: ₹X
Target 2: ₹X

Risk: Medium

Why:
3 independent signal families agree.
```

---

# 3. DO NOT MAKE UNSUPPORTED CLAIMS

The system must never say:

> “This stock WILL rise.”

Instead use language such as:

* “Bullish setup”
* “Bearish setup”
* “Potential opportunity”
* “Historical edge”
* “Signal strength”
* “Evidence supports”
* “Setup invalidated if…”
* “Low/medium/high confidence”

Every AI-generated conclusion must link back to underlying evidence.

---

# 4. TECH STACK

Use the following stack unless there is a strong technical reason to change it.

## Frontend

* Next.js
* TypeScript
* React
* Tailwind CSS
* shadcn/ui
* Recharts or equivalent
* TradingView Lightweight Charts where appropriate
* TanStack Query
* Zustand where client-side state is necessary

## Backend

Python

FastAPI

Pydantic

SQLAlchemy

Alembic

PostgreSQL

Redis

Celery or another reliable background-job system

## Data / quantitative layer

Python

pandas

NumPy

scikit-learn where appropriate

TA-Lib or an equivalent technical-analysis implementation

Statsmodels where useful

## AI

Use an LLM abstraction layer so the model provider can be changed without rewriting the application.

The AI layer should support:

* News classification
* Event extraction
* Sentiment analysis
* Catalyst identification
* Summarization
* Evidence extraction
* Historical-event comparison
* Natural-language explanations

Do NOT use an LLM for calculations that can be performed deterministically.

For example:

DO NOT ask the LLM to calculate RSI.

Calculate RSI in Python.

DO NOT ask the LLM to calculate position sizing.

Calculate it deterministically.

Use the LLM primarily for:

* Understanding unstructured information
* Classification
* Explanation
* Summarization
* Connecting evidence

---

# 5. ARCHITECTURE

Use this architecture:

```text
                    DATA SOURCES
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
      NEWS          MARKET DATA      COMPANY DATA
        │                │                │
        └────────────────┼────────────────┘
                         ▼
                 INGESTION SERVICES
                         │
                         ▼
                    NORMALIZATION
                         │
                         ▼
                  EVENT EXTRACTION
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          SENTIMENT   CATALYST   ENTITY
          ANALYSIS    ANALYSIS   LINKING
              │          │          │
              └──────────┼──────────┘
                         ▼
                 SIGNAL ENGINE
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
    TECHNICAL        FUNDAMENTAL       HISTORICAL
     SIGNALS           SIGNALS          ANALOGUES
        │                │                │
        └────────────────┼────────────────┘
                         ▼
                    RISK ENGINE
                         │
                         ▼
                  OPPORTUNITY SCORE
                         │
                         ▼
                    AI EXPLANATION
                         │
                         ▼
                    WEB FRONTEND
```

---

# 6. PROJECT STRUCTURE

Create a clean monorepo:

```text
marketpulse-ai/
│
├── apps/
│   ├── web/
│   └── api/
│
├── services/
│   ├── market-data/
│   ├── news-ingestion/
│   ├── event-engine/
│   ├── signal-engine/
│   ├── backtesting/
│   └── notifications/
│
├── packages/
│   ├── shared-types/
│   ├── indicators/
│   ├── scoring/
│   └── config/
│
├── infrastructure/
│   ├── docker/
│   └── deployment/
│
├── scripts/
│
├── tests/
│
├── docs/
│
├── docker-compose.yml
├── .env.example
├── README.md
└── Makefile
```

Keep the system modular.

Do not create a giant monolithic Python file.

---

# 7. DATA SOURCE ABSTRACTION

Create interfaces for all external data providers.

For example:

```python
class MarketDataProvider(Protocol):
    async def get_quote(self, symbol: str): ...
    async def get_historical_prices(self, symbol: str, start, end): ...
    async def get_intraday_prices(self, symbol: str): ...


class NewsProvider(Protocol):
    async def get_latest_news(self): ...
    async def search_news(self, query: str): ...


class CorporateDataProvider(Protocol):
    async def get_announcements(self): ...
    async def get_results(self, symbol: str): ...
```

Do not hard-code the application to one provider.

Use environment variables for API keys.

Provide:

1. Real provider adapters where credentials are available.
2. Mock/demo providers so the entire application works without paid APIs.

Never fabricate real-time market data.

Clearly mark demo/mock data in the UI.

---

# 8. CORE DATABASE MODEL

Use PostgreSQL.

Create models for at least:

## User

```text
id
email
name
created_at
updated_at
```

## Stock

```text
id
symbol
exchange
company_name
sector
industry
isin
market_cap
is_active
created_at
updated_at
```

## PriceBar

```text
id
stock_id
timestamp
timeframe
open
high
low
close
volume
vwap
```

## NewsArticle

```text
id
source
title
url
published_at
content
language
author
hash
created_at
```

## NewsEvent

```text
id
article_id
event_type
event_subtype
impact_score
sentiment_score
confidence
summary
created_at
```

## StockEvent

```text
id
stock_id
event_id
relevance_score
direction
created_at
```

## TechnicalSnapshot

```text
stock_id
timestamp
rsi
macd
macd_signal
ema_20
ema_50
ema_200
atr
adx
vwap
relative_volume
price_change_5m
price_change_15m
price_change_1h
price_change_1d
```

## Signal

```text
id
stock_id
timestamp
direction
score
confidence
catalyst_score
technical_score
volume_score
momentum_score
historical_score
risk_score
status
explanation
```

## TradeSetup

```text
id
signal_id
entry_low
entry_high
stop_loss
target_1
target_2
risk_reward
invalidated_at
created_at
```

## HistoricalEvent

```text
id
stock_id
event_type
event_timestamp
event_description
price_before
price_after_15m
price_after_1h
price_after_1d
price_after_5d
volume_change
```

## Watchlist

## Alert

## UserPreference

---

# 9. NEWS INGESTION ENGINE

Create a background worker that periodically retrieves new news.

Pipeline:

```text
Fetch
 ↓
Deduplicate
 ↓
Normalize
 ↓
Identify companies
 ↓
Classify event
 ↓
Calculate sentiment
 ↓
Calculate impact
 ↓
Store
 ↓
Generate stock signals
```

News should be categorized into:

* Earnings
* Revenue
* Profit warning
* Guidance
* Management change
* M&A
* Acquisition
* Partnership
* Contract win
* Order win
* Regulatory approval
* Regulatory action
* Government policy
* Product launch
* Litigation
* Debt
* Credit rating
* Dividend
* Buyback
* Promoter activity
* Insider activity
* FII/DII activity
* Brokerage upgrade
* Brokerage downgrade
* Sector news
* Macro news
* Commodity shock
* Currency shock
* Geopolitical event
* Other

Allow multiple event types.

---

# 10. ENTITY RESOLUTION

The same company can appear under:

```text
Reliance
Reliance Industries
RIL
RELIANCE
NSE:RELIANCE
```

Create an entity-resolution layer that maps all variants to:

```text
stock_id
```

Use:

* ticker mapping
* company names
* aliases
* fuzzy matching
* deterministic mappings

Do NOT rely solely on an LLM.

---

# 11. NEWS SENTIMENT

Create a structured output:

```json
{
  "sentiment": "bullish",
  "sentiment_score": 0.82,
  "impact_score": 0.91,
  "event_type": "earnings",
  "time_horizon": "short_term",
  "confidence": 0.88,
  "reasoning": "...",
  "evidence": []
}
```

Sentiment should NOT equal trading direction automatically.

For example:

Good news + extremely overbought price

may result in:

```text
News: Bullish
Trade setup: Neutral / high-risk
```

---

# 12. CATALYST ENGINE

Every major news event should receive a catalyst score from 0–10.

Factors:

* Materiality
* Surprise
* Recency
* Credibility
* Historical impact
* Company relevance
* Sector relevance
* Market sensitivity

Example:

```text
Major earnings beat:
9.2/10

Minor management comment:
3.1/10
```

The scoring must be deterministic/reproducible wherever possible.

---

# 13. TECHNICAL ANALYSIS ENGINE

Calculate at least:

* RSI
* MACD
* EMA 20
* EMA 50
* EMA 200
* SMA 20
* SMA 50
* ATR
* ADX
* VWAP
* Bollinger Bands
* Relative Volume
* Price momentum
* Gap percentage
* Distance from day high
* Distance from day low
* Support levels
* Resistance levels
* Breakout detection
* Breakdown detection

Timeframes:

* 1 minute
* 5 minute
* 15 minute
* 1 hour
* Daily

The application must allow indicators to be configured.

---

# 14. MARKET REGIME ENGINE

Determine whether the market is:

```text
Strong Bull
Bull
Neutral
Bear
Strong Bear
```

Use:

* NIFTY
* BANK NIFTY
* sector indices
* breadth
* volatility
* volume
* market momentum

Signals should be adjusted according to market regime.

Example:

A marginal bullish stock setup during a severe market-wide selloff should receive a lower confidence score.

---

# 15. SECTOR ENGINE

Track sectors such as:

* Banking
* IT
* Pharma
* Auto
* FMCG
* Energy
* Metals
* Realty
* Telecom
* Infrastructure
* Chemicals
* Financial Services

Calculate:

* Sector momentum
* Relative strength
* Sector breadth
* Sector news
* Leading stocks
* Lagging stocks

Detect:

```text
Sector Rotation
```

Example:

```text
IT sector +2.1%
NIFTY +0.3%

=> Strong relative strength
```

---

# 16. VOLUME ANALYSIS

Calculate:

```text
relative_volume =
current_volume / average_volume
```

Detect:

* Volume breakout
* Volume exhaustion
* Accumulation
* Distribution
* Unusual activity

Flag:

```text
Relative Volume > 2x
```

as an important event.

---

# 17. SIGNAL ENGINE

Create a transparent scoring system.

Initial model:

```text
Overall Score =
    25% Catalyst
    20% Technical
    15% Momentum
    15% Volume
    10% Historical Edge
    10% Market Regime
     5% Risk Quality
```

Make weights configurable.

Every score should be inspectable.

Example:

```text
RELIANCE

Catalyst             92
Technical             81
Momentum              77
Volume                88
Historical Edge       73
Market Regime         69
Risk Quality          80

Overall               82
```

---

# 18. SIGNAL CATEGORIES

Generate:

```text
BULLISH
BEARISH
WATCH
NO SIGNAL
```

Do not force a signal.

Most stocks should have:

```text
NO SIGNAL
```

A good signal engine should be selective.

---

# 19. SIGNAL QUALITY FILTER

Do NOT show every signal.

Minimum requirements could include:

```text
score >= 70
AND
confidence >= 65
AND
liquidity threshold satisfied
AND
data quality sufficient
```

Make these configurable.

---

# 20. TRADE SETUP ENGINE

For qualifying signals calculate:

```text
Entry Zone
Stop Loss
Target 1
Target 2
Risk/Reward
Invalidation Condition
```

Use deterministic formulas.

Example:

```text
ATR-based stop

stop_distance = ATR × multiplier
```

Allow configuration:

```text
ATR multiplier:
1.0
1.5
2.0
```

Targets can be based on:

* Risk/reward
* Resistance
* ATR
* Support/resistance
* Historical volatility

Never invent prices.

---

# 21. POSITION SIZING

Allow the user to configure:

```text
Capital
Risk per trade %
Maximum position %
Maximum daily loss
```

Calculate:

```text
risk_amount = capital × risk_percent

position_size =
risk_amount / abs(entry - stop_loss)
```

Display:

```text
Suggested quantity
Capital required
Maximum loss
Potential profit
Risk/reward
```

---

# 22. HISTORICAL ANALOGUE ENGINE

This is one of the most important features.

When a major event occurs, search historical events with similar:

* Event type
* Sentiment
* Catalyst magnitude
* Company characteristics
* Market regime
* Volatility
* Volume behavior

Calculate subsequent returns:

```text
15 minutes
30 minutes
1 hour
1 day
5 days
```

Display:

```text
Historical analogues found: 43

15m:
Win rate 61%
Median return +0.38%

1h:
Win rate 67%
Median return +0.72%

1D:
Win rate 64%
Median return +1.41%
```

Clearly label this as historical analysis, NOT a prediction.

---

# 23. BACKTESTING ENGINE

Build a backtesting framework.

Users should be able to test:

```text
Signal score > 75
Catalyst > 7
Relative volume > 2
RSI between 50 and 70
Market regime Bull
```

Measure:

* Win rate
* Average return
* Median return
* Profit factor
* Sharpe ratio
* Maximum drawdown
* Number of trades
* Average holding time
* Expectancy

Support:

```text
No look-ahead bias
No survivorship bias where possible
Transaction costs
Slippage
Brokerage
Taxes/fees
```

This is extremely important.

---

# 24. BACKTEST UI

Create:

**Strategy Lab**

Users can select:

```text
Date range
Universe
Signal threshold
Indicators
Catalyst threshold
Holding period
Stop method
Target method
```

Then show:

```text
Backtest Result

Trades: 1,284
Win Rate: 61.2%
Profit Factor: 1.73
Average Trade: +0.64%
Max Drawdown: -8.7%
Expectancy: +0.31%
```

Also show an equity curve.

---

# 25. MAIN DASHBOARD

Create a professional trading dashboard.

Layout:

```text
┌──────────────────────────────────────────────────────────────┐
│ MarketPulse AI                       Market: OPEN            │
├──────────────────────────────────────────────────────────────┤
│ NIFTY       BANK NIFTY       INDIA VIX       MARKET REGIME   │
│ +0.72%      +1.14%           -2.3%          BULL             │
├──────────────────────────────────────────────────────────────┤
│                  TOP OPPORTUNITIES                            │
│                                                              │
│ RELIANCE    🟢 Bullish     84     High catalyst              │
│ HDFCBANK    🟢 Bullish     81     Breakout                   │
│ INFY        🟢 Bullish     77     Earnings                    │
│ TATASTEEL   🔴 Bearish     74     Sector weakness             │
├──────────────────────────────────────────────────────────────┤
│                 MARKET MOVERS                                 │
│                                                              │
│ Top Gainers | Top Losers | Volume Spikes | Breakouts         │
├──────────────────────────────────────────────────────────────┤
│                     LATEST EVENTS                             │
│                                                              │
│ 09:41 RELIANCE — Earnings update — Impact 9/10               │
│ 09:37 INFY — Analyst upgrade — Impact 6/10                   │
│ 09:32 BANKING — RBI-related news — Impact 8/10               │
└──────────────────────────────────────────────────────────────┘
```

---

# 26. STOCK DETAIL PAGE

For every stock create:

```text
Header
Price
Change
Volume
Signal
Signal score
```

Then:

### Chart

Candlestick chart with:

* EMA
* VWAP
* Volume
* Signal markers

### News

Chronological news feed.

### AI analysis

```text
Why is this stock moving?
```

### Technical

All indicators.

### Fundamentals

Important company metrics.

### Historical behaviour

Similar news events.

### Trade setup

Entry / stop / target.

### Risk

Risk assessment.

### Evidence

Every important conclusion should have supporting data.

---

# 27. “WHY IS THIS STOCK MOVING?” FEATURE

This should be a flagship feature.

User clicks:

**Why is RELIANCE moving +3.8%?**

Return:

```text
PRIMARY DRIVER

Positive earnings announcement
Impact: 9/10

SECONDARY DRIVERS

Energy sector strength
Impact: 6/10

Technical confirmation
Impact: 8/10

Volume
2.4x average

MARKET CONTEXT
NIFTY +0.4%

AI CONCLUSION

The move appears primarily catalyst-driven,
with technical and volume confirmation.

Signal:
BULLISH

Confidence:
84%
```

---

# 28. AI MARKET COPILOT

Add a conversational interface.

Users can ask:

```text
Why is Tata Motors moving?

Which stocks have unusual volume today?

Show bullish stocks with strong catalysts.

What are today's biggest market-moving events?

Which sectors are strongest?

What changed in the market since yesterday?

Find stocks breaking out with volume confirmation.

Explain why HDFC Bank is bullish.

Show me bearish setups.

What happened after similar events historically?
```

The AI must retrieve real application data before answering.

Never allow it to invent market information.

---

# 29. ALERT SYSTEM

Allow alerts for:

```text
News event
Stock signal
Price threshold
Volume spike
Breakout
Breakdown
Score threshold
Watchlist event
```

Example:

```text
Alert me when:
Any NSE stock
Signal score > 80
AND
Relative volume > 2
AND
Catalyst score > 7
```

Notifications can initially be:

* In-app
* Email

Design abstraction for:

* Telegram
* WhatsApp
* Push notifications

later.

---

# 30. WATCHLIST

Users can create:

```text
My Stocks
Breakout Watch
Earnings Watch
High Volatility
F&O Watch
```

Watchlist rows:

```text
Symbol
Price
Change
Volume
Signal
Score
Catalyst
Technical
```

---

# 31. NEWS TERMINAL

Create a dedicated news page.

Filters:

```text
All
Market
Stocks
Earnings
Corporate
Government
RBI
SEBI
FII/DII
Brokerage
Sector
Global
```

Each news item:

```text
Headline
Source
Timestamp
Affected stocks
Event type
Sentiment
Impact
AI summary
```

---

# 32. DATA QUALITY

Every data source must have:

```text
source
timestamp
data_age
confidence
```

Show:

```text
Data updated 8 seconds ago
```

or:

```text
Delayed data
```

Never imply real-time data when the provider is delayed.

---

# 33. MARKET HOURS

Implement Indian market hours and timezone:

```text
Asia/Kolkata
```

Handle:

* Pre-market
* Market open
* Market close
* Post-market
* Weekends
* NSE/BSE holidays

Do not hard-code holidays permanently.

Create a market-calendar abstraction.

---

# 34. SECURITY

Implement:

* Authentication
* Password hashing
* JWT/session handling
* Rate limiting
* Input validation
* Secure API keys
* Environment-based configuration
* CORS
* CSRF protection where appropriate
* SQL injection protection
* Audit logging

Never expose provider API keys to the browser.

---

# 35. OBSERVABILITY

Add:

* Structured logging
* Error tracking abstraction
* Health endpoints
* Data pipeline status
* Job status
* Provider status

Create:

```text
/api/health
/api/health/data
/api/health/providers
```

---

# 36. ADMIN DASHBOARD

Create an admin-only area.

Display:

```text
News ingestion
Market data ingestion
Failed jobs
Provider status
API usage
Signals generated
Signals rejected
Data freshness
Database health
```

Allow manual:

```text
Reprocess news article
Recalculate stock signal
Re-run historical analysis
```

---

# 37. DESIGN SYSTEM

The application should look like a serious professional trading terminal.

Design characteristics:

* Dark-first UI
* Dense but readable information
* Excellent typography
* Clear hierarchy
* Minimal unnecessary decoration
* Green/red reserved for market direction
* Strong tables
* Keyboard-friendly navigation
* Responsive design

Do not make it look like a generic AI chatbot.

Think:

```text
Bloomberg Terminal
+
Modern SaaS
+
AI research assistant
```

but do NOT copy proprietary UI.

---

# 38. RESPONSIVE DESIGN

Desktop should be the primary experience.

Also support:

* Tablet
* Mobile

On mobile prioritize:

```text
Market status
Top signals
Alerts
Watchlist
News
Stock detail
```

---

# 39. API DESIGN

Create REST APIs such as:

```text
GET /api/market/overview

GET /api/stocks

GET /api/stocks/{symbol}

GET /api/stocks/{symbol}/chart

GET /api/stocks/{symbol}/news

GET /api/stocks/{symbol}/signals

GET /api/signals

GET /api/signals/{id}

GET /api/news

GET /api/sectors

GET /api/movers

GET /api/breakouts

GET /api/volume-spikes

POST /api/watchlists

GET /api/watchlists

POST /api/alerts

GET /api/alerts

POST /api/backtests

GET /api/backtests/{id}

POST /api/copilot/query
```

Use OpenAPI documentation.

---

# 40. REAL-TIME UPDATES

Use WebSockets or Server-Sent Events where appropriate.

The dashboard should update without requiring a page refresh.

Events:

```text
Price update
Signal update
News event
Alert
Market status
```

Design the frontend so polling can be used in development if real-time infrastructure is unavailable.

---

# 41. DEMO MODE

This is mandatory.

The application must run locally without paid API keys.

Create a realistic synthetic/demo data generator.

Generate:

* Stocks
* Prices
* News
* Volume
* Signals
* Historical events

Clearly label:

```text
DEMO DATA
```

Never present synthetic data as real market data.

---

# 42. SEED DATA

Include realistic demo data for at least:

```text
RELIANCE
HDFCBANK
ICICIBANK
INFY
TCS
SBIN
TATAMOTORS
BHARTIARTL
ITC
LT
AXISBANK
KOTAKBANK
MARUTI
SUNPHARMA
TATASTEEL
```

Add sectors and relationships.

---

# 43. TESTING

Write real tests.

At minimum:

### Unit tests

* RSI
* EMA
* ATR
* VWAP
* Relative volume
* Score calculation
* Position sizing
* Risk/reward
* Event classification
* Entity resolution

### Integration tests

* News ingestion
* Database
* Signal generation
* API endpoints

### Frontend tests

* Dashboard
* Stock page
* Filters
* Watchlist
* Alert creation

### Backtesting tests

Specifically test for:

**look-ahead bias**

Create tests that ensure future price data cannot influence historical signals.

---

# 44. DATA LEAKAGE PREVENTION

This is extremely important.

When generating a signal at:

```text
10:15 AM
```

the system must only use information available at or before:

```text
10:15 AM
```

Never use:

* Future prices
* Later news
* End-of-day values
* Future corporate information

in historical backtests.

Implement timestamp-aware data access.

---

# 45. PAPER TRADING

Add a paper-trading module.

Users can:

```text
Create virtual portfolio
Enter simulated trades
Set entry
Stop
Target
Track P&L
```

Do NOT connect real brokerage execution initially.

Architecture should allow future broker integrations.

---

# 46. PORTFOLIO RISK

Dashboard should show:

```text
Capital
Open positions
Daily P&L
Unrealized P&L
Risk exposure
Sector exposure
Maximum loss
```

Warn when:

```text
Too much exposure to one sector
Too many correlated positions
Daily loss limit reached
```

---

# 47. CORRELATION ENGINE

Calculate correlations between holdings.

Detect:

```text
High correlation
Sector concentration
Market concentration
```

Example:

```text
Portfolio Risk

Banking exposure: 42%
IT exposure: 8%
Energy exposure: 17%

Warning:
Banking concentration is high.
```

---

# 48. SCORING EXPLANABILITY

Every signal must expose:

```text
Why score = 82?

Catalyst       +22
Technical      +17
Momentum       +13
Volume         +14
Historical     +8
Market         +5
Risk           +3
----------------
Total          82
```

The user must be able to inspect this.

---

# 49. AI OUTPUT SCHEMA

Force the LLM to return structured JSON.

Example:

```json
{
  "summary": "",
  "event_type": "",
  "direction": "bullish|bearish|neutral",
  "confidence": 0,
  "catalyst_score": 0,
  "impact_score": 0,
  "time_horizon": "",
  "affected_stocks": [],
  "evidence": [],
  "risks": [],
  "invalidating_conditions": []
}
```

Validate with Pydantic/Zod.

Never trust raw LLM output.

---

# 50. AI HALLUCINATION PROTECTION

The AI must only make factual claims from retrieved application data.

If evidence is insufficient, respond:

```text
Insufficient evidence.
```

Do not invent:

* Prices
* News
* Earnings
* Analyst opinions
* Market statistics
* Historical returns

Every factual statement should have a source/reference internally.

---

# 51. SOURCE ATTRIBUTION

Every news article must retain:

```text
Source
Original URL
Published timestamp
```

When AI uses an article, show:

```text
Source:
Reuters
Published:
10:21 IST
```

Never remove attribution.

Respect provider licensing and terms.

Do not scrape websites where prohibited.

Build provider adapters instead.

---

# 52. FINANCIAL DISCLAIMER

The UI should clearly state:

```text
MarketPulse AI provides market information and analytical tools for research and educational purposes. Signals are not guaranteed predictions or personalized financial advice. Trading involves substantial risk, including loss of capital.
```

Do not make guaranteed-profit claims.

---

# 53. PERFORMANCE REQUIREMENTS

Target:

```text
Dashboard initial load < 2 seconds
API p95 < 500ms for common cached endpoints
Stock page < 2 seconds
News feed incremental updates < 1 second after ingestion
```

Use:

* Redis caching
* Database indexes
* Pagination
* Lazy loading
* Background processing

---

# 54. DATABASE INDEXING

Add indexes for:

```text
stock.symbol
pricebar.stock_id + timestamp
news.published_at
event.created_at
stock_event.stock_id + created_at
signal.score
signal.timestamp
historical_event.stock_id + event_type
```

Optimize queries after measuring.

---

# 55. SCHEDULER

Create scheduled jobs:

```text
Every few seconds:
market data

Every 15–60 seconds:
news

Every minute:
technical indicators

On major event:
signal generation

End of day:
historical statistics

Nightly:
backtest/cache jobs
```

Do not assume every provider supports the same frequency.

Make schedules configurable.

---

# 56. DEVELOPMENT EXPERIENCE

Provide:

```text
docker compose up
```

as the simplest way to start development.

It should launch:

```text
PostgreSQL
Redis
API
Worker
Frontend
```

Include:

```text
.env.example
```

with all required variables.

---

# 57. README

Create an excellent README containing:

* Product overview
* Architecture
* Screenshots/placeholders
* Installation
* Environment variables
* Running locally
* Database migrations
* Seed data
* Demo mode
* API documentation
* Testing
* Backtesting
* Data provider setup
* Production deployment

---

# 58. IMPLEMENTATION ORDER

Do NOT try to implement everything at once.

Work in phases.

## PHASE 1 — FOUNDATION

Build:

* Monorepo
* Docker
* PostgreSQL
* Redis
* FastAPI
* Next.js
* Authentication
* Database models
* Basic design system
* Demo data

Then verify the application runs.

## PHASE 2 — MARKET DATA

Build:

* Provider abstraction
* Demo provider
* Price storage
* Technical indicators
* Market overview
* Stock page
* Charts

## PHASE 3 — NEWS

Build:

* News provider abstraction
* News ingestion
* Deduplication
* Entity resolution
* Event classification
* News UI

## PHASE 4 — SIGNAL ENGINE

Build:

* Catalyst scoring
* Technical scoring
* Volume analysis
* Momentum
* Market regime
* Overall signal score
* Explainability

## PHASE 5 — TRADE SETUPS

Build:

* Entry
* Stop
* Targets
* Risk/reward
* Position sizing
* Risk engine

## PHASE 6 — HISTORICAL ANALYSIS

Build:

* Historical event storage
* Analogues
* Statistical analysis
* Historical outcomes

## PHASE 7 — BACKTESTING

Build:

* Strategy Lab
* Backtesting engine
* Performance metrics
* Equity curve
* Look-ahead protection

## PHASE 8 — AI COPILOT

Build:

* Retrieval layer
* Structured LLM responses
* Evidence citations
* Natural-language market analysis

## PHASE 9 — ALERTS

Build:

* Alert engine
* Notifications
* Watchlists

## PHASE 10 — PAPER TRADING

Build:

* Virtual portfolio
* Simulated orders
* P&L
* Risk dashboard

---

# 59. HOW YOU MUST WORK

Do NOT stop after creating a plan.

You must actually implement the project.

For each phase:

1. Inspect the existing repository.
2. Create/update files.
3. Implement functionality.
4. Run tests.
5. Run lint/type checks.
6. Fix errors.
7. Start the application where possible.
8. Verify the UI.
9. Continue to the next phase.

Do not repeatedly ask me for permission to proceed.

Make reasonable engineering decisions yourself.

Only stop and ask a question if a decision is genuinely impossible without my input.

---

# 60. CODE QUALITY

Follow:

* SOLID principles
* DRY
* Type safety
* Clear naming
* Small modules
* Dependency injection
* Strong validation
* Explicit error handling
* Good logging
* Proper database transactions

Do not create placeholder functions that silently do nothing.

If something cannot yet use real data, implement the interface and a functioning demo provider.

---

# 61. ERROR HANDLING

The UI must gracefully handle:

```text
Provider unavailable
Stale market data
Missing stock
LLM unavailable
Database unavailable
News parsing failure
Invalid API response
Rate limit
```

Never crash the entire dashboard because one data provider failed.

Use partial availability.

Example:

```text
Market data: LIVE
News: DELAYED
AI analysis: AVAILABLE
Options data: UNAVAILABLE
```

---

# 62. IMPORTANT TRADING LOGIC PRINCIPLE

Do not optimize the system for generating the maximum number of signals.

Optimize for:

**high-quality, explainable opportunities.**

It is completely acceptable for the dashboard to say:

```text
No high-confidence setups right now.
```

That is preferable to manufacturing signals.

---

# 63. FUTURE EXTENSIBILITY

Design interfaces for future:

* Options chain analysis
* Futures
* Broker integrations
* Automated paper trading
* Telegram alerts
* Mobile application
* Portfolio optimization
* ML prediction models
* Earnings prediction
* Insider trading analysis
* Institutional flow analysis
* Alternative data
* Global markets

Do not implement all of these now.

Build clean extension points.

---

# 64. FINAL ACCEPTANCE CRITERIA

The MVP is complete only when I can run:

```bash
docker compose up
```

and access a functioning application where I can:

1. View Indian market overview.
2. See NSE/BSE stocks.
3. View stock charts.
4. See technical indicators.
5. View news.
6. See news linked to affected stocks.
7. See bullish/bearish/watch signals.
8. Understand why a signal received its score.
9. See potential entry/stop/targets.
10. See risk/reward.
11. View historical analogues.
12. Create a watchlist.
13. Create alerts.
14. Ask the AI market copilot questions.
15. Run a backtest.
16. View paper trades.
17. See portfolio risk.
18. Run the entire system using demo data without paid API credentials.

---

# 65. FIRST TASK

Before writing large amounts of code:

1. Inspect the repository.
2. Determine whether this is a new or existing project.
3. Create a concise implementation plan.
4. Create the project structure.
5. Implement Phase 1.
6. Run the application.
7. Run tests.
8. Fix all errors.
9. Then proceed automatically through the remaining phases.

At the end of each phase, provide a short status report containing:

```text
PHASE:
STATUS:

Implemented:
- ...

Tests:
- ...

Known limitations:
- ...

Next:
- ...
```

Do not merely describe code.

**Write the code and build the application.**

The final result should feel like a serious professional market-intelligence terminal, not a toy stock dashboard.

**One important recommendation:** give Claude Code access to the repository and let it build this incrementally. Don't ask it to generate 100% of the code in one response—the phased instruction above is deliberately designed to make it implement, test, and fix the system as it goes.
