# Testing

The project has two kinds of automated tests: an **offline suite** (no network,
no database server, no token — runs anywhere in about 30 seconds) and a **live
suite** against the real Upstox API. Manual end-to-end checks are in
[Test Scenarios](../operations/test-scenarios.md).

## Running the tests

```bash
pytest tests/ -q --ignore=tests/test_live_upstox.py      # offline suite
pytest tests/test_reconcile.py -v                        # one file
pytest tests/ -k "squareoff or token" -q                 # by keyword
pytest tests/ -x                                         # stop at the first failure
pytest tests/ --cov=. --cov-report=html                  # coverage (needs pytest-cov)
```

Database tests use in-memory SQLite, so PostgreSQL is not needed. Tests that
need the downloaded instrument master skip themselves when it is missing.

## The offline suite

About 550 tests in 48 files. By area:

| Area | Files |
|---|---|
| Trading bot safety | `test_bot_position_safety.py` (MIS squareoff, one position per symbol, tick sanity, daily reset), `test_bot_state_persistence.py` (crash recovery), `test_reconcile.py` (broker reconciliation), `test_bot_live_refresh.py` |
| Tokens and config | `test_token_expiry.py` (03:30 IST rule), `test_upstox_auth.py`, `test_config_loader.py` (`.env` loading) |
| Market data | `test_upstox_data.py`, `test_upstox_feed.py` (incl. tick symbol labelling), `test_upstox_instruments.py`, `test_instrument_registry.py`, `test_instrument_isins.py`, `test_live_bars.py`, `test_market_hours.py`, `test_demo_ohlcv.py` |
| Indicators and features | `test_indicators.py`, `test_session_vwap.py`, `test_greeks.py`, `test_iv_surface.py` |
| Strategies | `test_strategies.py`, `test_range_breakout.py`, `test_microstructure.py`, `test_vix_strategy.py`, `test_options_strategies.py` |
| Risk and execution | `test_risk_manager.py`, `test_upstox_executor.py` (fills, cancellation of unfilled orders, product setting), `test_execution_nonblocking.py` |
| Backtesting | `test_backtester.py`, `test_backtester_mis_squareoff.py`, `test_backtest_lookahead.py`, `test_backtest_router.py`, `test_tune_weights.py` |
| ML | `test_ml_pipeline.py` (dataset, gate, retrain, settings edit) |
| Research library | `test_p6_p14.py` (HMM, Kalman, TFT, online learning, CVaR, beta-neutral, stress test, factor model, advanced features) |
| MarketPulse | `test_db_models.py`, `test_news_pipeline.py`, `test_composite_signal_engine.py`, `test_signal_timeframe.py`, `test_why_endpoint.py`, `test_copilot.py`, `test_ai_client.py`, `test_watchlists_and_alerts.py`, `test_portfolio_risk.py` |
| Scheduler and API | `test_scheduler.py`, `test_intraday_scheduler.py`, `test_intraday_ui_endpoints.py` |
| This handbook | `test_docs.py` — every manifest chapter exists, internal links and section anchors resolve, tables are well-formed |

Many files start with a docstring explaining the bug they guard against; read
it before changing a test.

## The live suite

`tests/test_live_upstox.py` (about 60 tests) calls the real API: connectivity,
LTP, full quotes, daily and intraday candles, instrument search, feature
building on live data, option chain, India VIX and the F&O ban list. It skips
itself without a token:

```bash
UPSTOX_ACCESS_TOKEN=<token> pytest tests/test_live_upstox.py -v
```

Some checks only pass during market hours (live prices, VWAP on today's
intraday bars). `python scripts/test_upstox.py` is a quicker interactive check
of the same API.

## Writing tests

- Follow the style of the neighbouring file. Most build synthetic OHLCV frames
  with NumPy (`np.random.default_rng(seed)` for reproducibility) and a
  `pd.date_range` index.
- **No network**: monkeypatch fetchers (`_fetch_ohlcv`, `requests.get`,
  `fetch_broker_quantities`) — see `test_ml_pipeline.py` and
  `test_reconcile.py`.
- **No writes to real directories**: use `tmp_path` for models, state files and
  caches.
- Bot behaviour is tested by calling the real `UpstoxTradingBot` methods on a
  small stand-in object (see `test_bot_position_safety.py`), since building a
  full bot needs credentials.
- Freeze time by monkeypatching `utils.timeutils.now_ist`.
- Put a one-paragraph docstring at the top saying what bug or behaviour the file
  protects.

## Continuous integration

```yaml
- run: pip install -r requirements.txt
- run: pytest tests/ -q --ignore=tests/test_live_upstox.py
```

Add `UPSTOX_ACCESS_TOKEN` as a secret to run the live suite too — remembering
it expires at 03:30 IST each day.
