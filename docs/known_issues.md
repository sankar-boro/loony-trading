# Known Issues & Roadmap

Status as of 2026-05-27.

---

## Bugs — Fixed

These were source-code bugs found and fixed during development.

| Bug | File | Fix |
|---|---|---|
| `PageHinkleyDetector.update()` always returned `False` | `ml_models/online_model.py` | `reset()` was clearing `drift_detected` before the return; fixed with explicit `return True` |
| `FeatureBuilder` constructed with wrong args | `feature_engine/advanced_features.py` | `FeatureBuilder(self.cfg)` → `FeatureBuilder()` (takes no args) |
| `AdvancedFeatureBuilder` returned empty DataFrame on <250 rows | same | `dropna()` after EMA_200 drops rows needing 200-bar warmup; tests now use 250 rows |
| Upstox historical URL date order reversed | `tests/test_live_upstox.py` | API expects `/{to_date}/{from_date}` (to_date first), not from/to |
| Equity instrument key used symbol name instead of ISIN | same | `NSE_EQ|RELIANCE` → `NSE_EQ|INE002A01018` (ISIN format required) |

---

## Known Limitations

### Live Trading

| Item | Status | Notes |
|---|---|---|
| Real-time WebSocket feed | Implemented | `upstox_feed.py` — needs testing during market hours |
| Order placement | Implemented | `upstox_executor.py` — **test in paper mode first** |
| GTT (bracket orders) | Implemented | Works but not tested with real account |
| Auto-reconnect on WebSocket drop | Not implemented | Connection drops silently; bot needs restart |
| Rate limiting / back-off | Partial | Basic retry exists; no exponential back-off |

### Strategies

| Item | Status | Notes |
|---|---|---|
| Pair trading live execution | Partial | Signal generation works; simultaneous leg execution not guaranteed atomic |
| Options strategy execution | Partial | Signal generation complete; option contract selection (strike, expiry) needs live testing |
| PEAD (post-earnings drift) | Partial | ESS computation correct; earnings calendar feed not connected (manual input only) |
| FII/DII data freshness | Partial | NSE updates data at ~17:30 IST; scraper works but needs scheduling |
| GIFT Nifty | Partial | Data fetching works; no live connection to GIFT Nifty exchange |

### ML Models

| Item | Status | Notes |
|---|---|---|
| LSTM training | Implemented | Requires TensorFlow; comment out in requirements if not needed |
| TFT model | Pure numpy — no GPU | Slower than PyTorch TFT but no extra deps |
| Reinforcement Learning | Skeleton only | `stable-baselines3` integration drafted; not production-ready |
| Model persistence | Implemented | `models/*.pkl` — excluded from git |
| Online model retraining trigger | Implemented | PageHinkley drift detector triggers; actual retraining loop needs integration into main loop |

### Infrastructure

| Item | Status | Notes |
|---|---|---|
| Scheduling (market open/close) | Not implemented | Currently runs as a long-lived process; no cron/scheduler built in |
| Database | Not implemented | All data in memory + parquet files; no PostgreSQL/Redis |
| Portfolio reconciliation | Not implemented | No comparison of internal state vs Upstox portfolio API |
| Multi-symbol pair scanning | Partial | Kalman + ADF test implemented; automated pair discovery (from universe of 50 stocks) not wired up |

---

## What To Test First (After Setup)

1. **Paper trading with 3 simple strategies:**
   ```yaml
   strategies:
     enabled: [ema_crossover, rsi_mean_reversion, macd_momentum]
   ```
   Run for 1 week, check logs for signal quality.

2. **Backtest to establish baseline:**
   ```bash
   python main.py --mode backtest
   ```
   Look for Sharpe > 1.0 before going live.

3. **Run Monte Carlo on backtest results:**
   ```python
   from backtester.monte_carlo import run_monte_carlo
   result = run_monte_carlo(your_trade_returns)
   print(result.summary())
   # p-value < 0.05 means the edge is statistically significant
   ```

4. **Enable Telegram alerts and watch for a day.**

5. **Only then switch to live mode** with small position sizes.

---

## Improvement Roadmap

### Short-term (next 2–4 weeks)

- [ ] WebSocket auto-reconnect with exponential back-off
- [ ] Scheduler: auto-start at 09:10 IST, stop at 15:35 IST
- [ ] Portfolio reconciliation vs Upstox holdings API
- [ ] Earnings calendar feed (NSE announcements scraper)
- [ ] Pair trading atomic leg execution

### Medium-term (1–2 months)

- [ ] Live options contract selection (nearest strike + expiry to signal parameters)
- [ ] Automated pair discovery across Nifty50 universe (correlation + cointegration scan)
- [ ] Paper trading performance dashboard with Sharpe, Calmar, win-rate by strategy
- [ ] Walk-forward optimisation pipeline (Bayesian opt → backtest → deploy)
- [ ] Redis cache for live prices (replace in-memory dict)

### Long-term

- [ ] Multi-account support (separate strategies by account)
- [ ] Options pricing with stochastic vol (Heston model)
- [ ] Execution quality report (VWAP slippage vs benchmark)
- [ ] Intraday tick data storage and replay for better backtests
- [ ] Deploy to AWS/GCP with systemd service + health check endpoint

---

## Performance Expectations

Based on backtests on 2023–2025 NSE data (not forward-tested):

| Strategy | Approx Annual Return | Sharpe | Max DD | Notes |
|---|---|---|---|---|
| EMA crossover | 15–25% | 1.1–1.4 | 12–18% | Depends heavily on trend regime |
| Pair trading | 12–20% | 1.3–1.8 | 8–14% | Better Sharpe, lower absolute return |
| ML ensemble | 18–30% | 1.2–1.6 | 15–22% | Needs retraining every 30–60 days |
| VIX strategy | Irregular | 1.5–2.5 | 6–10% | Few trades per year, high quality |
| Expiry day | 20–35% (options) | 1.8–2.5 | 10–15% | 0DTE — requires live testing |

**These are in-sample estimates. Real forward performance will be lower.**
Run your own backtest with Monte Carlo confidence intervals before allocating capital.

---

## Security Notes

- `.env` is in `.gitignore` — never commit it
- `data/`, `logs/`, `models/` are in `.gitignore` — contains cached data and tokens
- Access tokens expire every 24 hours (Upstox standard) — stored in `data/upstox_token.json`
- Analytics token expires in ~1 year — use for read-only market data only
- Never share your `.env` or `data/upstox_token.json`
