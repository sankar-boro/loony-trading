# Testing Guide

483 offline tests + 60 live Upstox API tests. All offline tests pass as of 2026-10-09.

---

## Running All Tests

```bash
# Run everything offline (~30 seconds)
pytest tests/ -v --ignore=tests/test_live_upstox.py

# Run with short output
pytest tests/ -q

# Run and stop on first failure
pytest tests/ -x

# Run with coverage report
pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html
```

---

## Test Suites

| File | Tests | What it covers |
|---|---|---|
| `test_strategies.py` | ~30 | Base strategy, signal generation, meta engine |
| `test_indicators.py` | ~25 | RSI, MACD, ATR, Bollinger, EMA calculations |
| `test_risk_manager.py` | ~20 | Position sizing, stop-loss, drawdown guard |
| `test_greeks.py` | ~15 | Black-Scholes delta/gamma/theta/vega, IV solver |
| `test_iv_surface.py` | ~15 | IV surface construction, ATM IV, skew |
| `test_microstructure.py` | ~15 | Cumulative delta, volume profile, anchored VWAP |
| `test_options_strategies.py` | ~15 | Iron condor, gamma scalp, theta, expiry |
| `test_backtester.py` | ~10 | Event-driven backtest, walk-forward validation |
| `test_vix_strategy.py` | ~18 | VIX classification, spike reversal, regime |
| `test_market_hours.py` | ~10 | NSE open/close detection, holiday handling |
| `test_upstox_auth.py` | ~8 | Token lifecycle, refresh logic |
| `test_upstox_data.py` | ~10 | Historical data fetching (mocked) |
| `test_upstox_executor.py` | ~10 | Order placement, GTT, error handling |
| `test_upstox_feed.py` | ~8 | WebSocket feed parsing |
| `test_upstox_instruments.py` | ~8 | Instrument key resolution |
| `test_p6_p14.py` | 106 | HMM, Kalman, TFT, online learning, CVaR, beta-neutral, stress test, factor model, advanced features |
| `test_live_bars.py`, `test_bot_live_refresh.py` | — | Live bar aggregator, live tick loop data refresh |
| `test_session_vwap.py`, `test_range_breakout.py` | — | Session-anchored VWAP, opening range breakout |
| `test_backtester_mis_squareoff.py`, `test_backtest_lookahead.py` | — | MIS squareoff in backtests, look-ahead bias |
| `test_execution_nonblocking.py` | — | Order I/O runs off the event loop |
| `test_signal_timeframe.py`, `test_intraday_scheduler.py`, `test_intraday_ui_endpoints.py` | — | Intraday signals, scheduler track, endpoints |
| `test_composite_signal_engine.py`, `test_why_endpoint.py` | — | Composite scoring, "why is it moving" |
| `test_news_pipeline.py`, `test_ai_client.py`, `test_copilot.py` | — | News ingestion/classification, AI client, Copilot |
| `test_watchlists_and_alerts.py`, `test_portfolio_risk.py` | — | Watchlists, alerts, portfolio risk |
| `test_scheduler.py`, `test_db_models.py`, `test_backtest_router.py`, `test_demo_ohlcv.py` | — | Scheduler, DB models, backtest API, demo data |
| `test_bot_position_safety.py`, `test_token_expiry.py` | — | MIS squareoff, one position per symbol, 03:30 IST token expiry |
| `test_live_upstox.py` | 60 | **Live Upstox API** (requires token) |

---

## Running Specific Tests

```bash
# Single file
pytest tests/test_p6_p14.py -v

# Single test class
pytest tests/test_p6_p14.py::TestHMMRegime -v

# Single test
pytest tests/test_p6_p14.py::TestHMMRegime::test_fit_and_predict -v

# All tests matching a keyword
pytest tests/ -k "kalman" -v
pytest tests/ -k "vix" -v
pytest tests/ -k "pair_trading" -v
```

---

## Live API Tests

These tests hit the real Upstox API. They require an access token set as an environment variable.

```bash
export UPSTOX_ACCESS_TOKEN=your_token_here
pytest tests/test_live_upstox.py -v
```

Or inline:
```bash
UPSTOX_ACCESS_TOKEN=your_token pytest tests/test_live_upstox.py -v
```

**Getting a token:**
1. Log in to Upstox developer console
2. Generate an Analytics token (read-only, valid ~1 year)
3. Or run `python main.py --mode auth` for a full trading token

### What the live tests cover

```
TestAPIConnectivity      — token valid, LTP endpoint returns 200, JSON is valid
TestLTP                  — Nifty50 / BankNifty / NiftyIT / MidCap LTP, bulk fetch
TestFullQuotes           — OHLC, bid/ask depth, multiple indices
TestHistoricalDaily      — 30d/60d candles, weekly, monthly, 2 years back
TestIntradayCandles      — 1-minute, 30-minute intraday data
TestInstrumentSearch     — RELIANCE, TCS, HDFC search, ISIN verification
TestDataEngineWithLiveData  — FeatureBuilder, CVaR, beta, factor model, Kalman,
                              circuit detector, Monte Carlo on live Nifty data
TestLiveTechnicalAnalysis   — RSI, MACD, Bollinger, ATR, EMA, cumulative delta,
                              volume profile (VWAP skips outside market hours)
TestOptionsData          — option chain endpoint probe, live-spot Greeks, IV surface
TestNSEDataEngine        — India VIX fetch, VIX percentile, F&O ban list
```

### Expected results

- **59 pass, 1 skip** — VWAP test skips outside market hours (09:15–15:30 IST)
  because intraday candles return zero volume when market is closed
- During market hours (run between 09:15–15:30 IST): **60/60 pass**

---

## Reading Logs During Tests

Tests write to console. To also capture to a log file:

```bash
pytest tests/ -v 2>&1 | tee logs/test_run.log
```

To run live tests and see full request/response details (debug mode):

```bash
LOG_LEVEL=DEBUG UPSTOX_ACCESS_TOKEN=your_token pytest tests/test_live_upstox.py -v -s
```

The `-s` flag disables stdout capture so you see all print statements and log lines.

---

## Manual API Verification

Quickly verify your token is working:

```python
import os, requests
TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN")
r = requests.get(
    "https://api.upstox.com/v2/market-quote/ltp",
    params={"instrument_key": "NSE_INDEX%7CNifty%2050"},
    headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
)
print(r.status_code, r.json())
```

Expected: `200 {'status': 'success', 'data': {'NSE_INDEX:Nifty 50': {'last_price': 23914.15}}}`

---

## Writing New Tests

All test files follow this pattern:

```python
import pytest
import numpy as np
import pandas as pd

def _make_ohlcv(n=100) -> pd.DataFrame:
    """Helper: synthetic OHLCV data."""
    rng = np.random.RandomState(42)
    close = 1000 + np.cumsum(rng.randn(n))
    df = pd.DataFrame({
        "open":   close * 0.999,
        "high":   close * 1.005,
        "low":    close * 0.995,
        "close":  close,
        "volume": rng.randint(100000, 500000, n).astype(float),
    })
    return df

class TestMyFeature:
    def test_basic(self):
        df = _make_ohlcv()
        # ... assert things
```

For live tests, use the skip pattern:
```python
import os
pytestmark = pytest.mark.skipif(
    not os.environ.get("UPSTOX_ACCESS_TOKEN"),
    reason="UPSTOX_ACCESS_TOKEN not set"
)
```

---

## Continuous Integration

To run tests in CI (GitHub Actions / similar):

```yaml
- name: Run tests
  env:
    UPSTOX_ACCESS_TOKEN: ${{ secrets.UPSTOX_ACCESS_TOKEN }}
  run: |
    pip install -r requirements.txt
    pytest tests/ -v --ignore=tests/test_live_upstox.py   # skip live in CI
    # Or include live tests if token is set:
    pytest tests/test_live_upstox.py -v
```
