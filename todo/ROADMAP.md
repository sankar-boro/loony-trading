# Loony Trading Bot — Full Roadmap

## TIER 1 — Direct Alpha (Priority 1–5, implement first)

### P1: Options Greeks + IV Surface + Theta Decay Strategy  ✅ DONE
- [ ] `feature_engine/greeks.py` — Delta, Gamma, Theta, Vega, Vanna, Charm calculators (Black-Scholes + numerical)
- [ ] `data_engine/upstox/iv_surface.py` — IV rank/percentile, volatility surface, term structure builder
- [ ] `strategies/options/__init__.py`
- [ ] `strategies/options/theta_decay.py` — Sell OTM options, collect premium (weekly/monthly expiry)
- [ ] `strategies/options/iron_condor.py` — Nifty/BankNifty range-bound plays (weekly expiry)
- [ ] `strategies/options/straddle_strangle.py` — Buy before events, sell after IV crush
- [ ] `strategies/options/gamma_scalping.py` — Delta-hedge and scalp gamma on expiry day
- [ ] Max pain calculation integrated into strategy signals (not just dashboard)
- [ ] Weekly expiry pinning signal (BankNifty Thursday, Nifty monthly)

### P2: FII/DII + Delivery Data + F&O Ban List  ✅ DONE
- [ ] `data_engine/nse_data.py` — Scrape NSE FII/DII cash + F&O data (published daily 18:00 IST)
- [ ] FII index futures net position → directional bias for next day
- [ ] FII options OI changes → market maker hedging pressure
- [ ] Delivery volume % per stock (genuine accumulation signal)
- [ ] F&O ban list checker (daily, before any order placement)
- [ ] `strategies/institutional/fii_dii_strategy.py` — Trade direction aligned with FII net flows

### P3: India VIX Strategy  ✅ DONE
- [ ] `data_engine/upstox/india_vix.py` — Fetch India VIX real-time + historical via Upstox
- [ ] `strategies/volatility/__init__.py`
- [ ] `strategies/volatility/vix_strategy.py`
  - VIX > 20 + rising → sell straddle / buy put spreads
  - VIX < 12 + falling → sell iron condors
  - VIX spike > 3% intraday → mean reversion buy
- [ ] VIX term structure arbitrage
- [ ] VIX / Nifty correlation divergence signal

### P4: Cumulative Delta + Volume Profile  ✅ DONE
- [ ] `strategies/microstructure/cumulative_delta.py` — Aggressive buy/sell classification tick by tick
- [ ] `strategies/microstructure/volume_profile.py` — POC, VAH, VAL calculation per session
- [ ] `strategies/microstructure/trade_tape.py` — Tick classification (uptick=buy, downtick=sell)
- [ ] `strategies/microstructure/anchored_vwap.py` — Per-session anchored VWAP with ±1σ, ±2σ bands
- [ ] Integrate volume profile levels as dynamic S/R into all strategies

### P5: GIFT Nifty Pre-Market Feed  ✅ DONE
- [ ] `data_engine/gift_nifty.py` — Fetch GIFT Nifty (NSE IFSC) pre-market data
- [ ] `strategies/gap/gift_nifty_gap.py`
  - Gap-up > 0.5%: fade the open (short first 15 min), then follow trend
  - Gap-down < -0.5%: same logic inverted
  - Pre-market bias signal injected into meta engine before 9:15 IST
- [ ] GIFT vs Spot premium/discount convergence model

---

## TIER 2 — Structural ML Improvements (Priority 6–10)

### P6: Hidden Markov Model Regime Detection
- [ ] `strategies/hmm_regime.py` — 6-state HMM trained per instrument
- [ ] Regime transition probability matrix
- [ ] Replace/augment ADX-based regime detector in meta engine

### P7: Kalman Filter for Pair Trading
- [ ] `utils/kalman.py` — Kalman filter implementation
- [ ] Replace rolling OLS hedge ratio in `strategies/stat_arb/pair_trading.py`
- [ ] Dynamic spread mean + variance tracking

### P8: Temporal Fusion Transformer (TFT)
- [ ] `ml_models/tft_model.py` — Multi-horizon forecasting with attention
- [ ] Multi-horizon output: 5m, 15m, 30m predictions simultaneously
- [ ] Variable importance / attention weights for interpretability
- [ ] Integrate into ensemble model

### P9: Online / Incremental Learning
- [ ] `ml_models/online_model.py` — River-based incremental models
- [ ] Concept drift detector (ADWIN / Page-Hinkley)
- [ ] Per-tick model weight update
- [ ] Auto-retrain trigger when drift detected

### P10: Advanced Feature Engineering
- [ ] Cross-asset features: USD/INR, Gold, Crude Oil, US futures
- [ ] F&O OI build-up / unwinding ratio per strike
- [ ] Put/Call ratio (PCR) at various strikes
- [ ] Delivery volume ratio (genuine vs intraday)
- [ ] Options skew: 25-delta risk reversal
- [ ] Max pain distance (how far spot is from max pain)

---

## TIER 3 — Risk & Portfolio Gaps (Priority 11–14)

### P11: CVaR / Expected Shortfall
- [ ] `risk_manager/cvar.py` — CVaR at 95% and 99% confidence levels
- [ ] Historical simulation + parametric methods
- [ ] Replace max-drawdown as primary risk limit with CVaR

### P12: Factor Risk Decomposition
- [ ] `analytics/factor_model.py` — Fama-French + momentum + quality factors
- [ ] India-specific: IT/FMCG/Banking factor exposure tracking
- [ ] Auto-hedge with Nifty futures when net beta exceeds threshold

### P13: Beta-Neutral Portfolio Construction
- [ ] `portfolio_manager/beta_neutral.py`
- [ ] Rolling beta computation vs Nifty 50
- [ ] Auto Nifty futures hedge sizing
- [ ] Track pure alpha vs market beta contribution

### P14: Stress Testing
- [ ] `backtester/stress_test.py`
- [ ] Scenario replays: COVID 2020, 2015 China crash, 2018 NBFC crisis
- [ ] Per-strategy max drawdown under each scenario
- [ ] Tail risk report generation

---

## TIER 4 — India-Specific Missing Pieces (Priority 15–18)

### P15: NSE Corporate Actions Calendar
- [ ] `data_engine/nse_data.py` — Ex-dividend, bonus, split, rights issue calendar
- [ ] Auto-adjust position sizing on ex-date
- [ ] Avoid holding naked overnight before earnings
- [ ] Earnings date signal generator (PEAD momentum)

### P16: Expiry Day Strategy
- [ ] `strategies/options/expiry_strategy.py`
- [ ] BankNifty 0DTE scalping (Thursday only)
- [ ] Gamma squeeze detection near expiry
- [ ] Pinning to max pain in last 30 minutes

### P17: F&O Securities Ban List
- [ ] Daily NSE ban list fetch and cache
- [ ] Block any new F&O order for banned securities
- [ ] Alert when existing position is in a stock entering ban

### P18: Circuit Breaker Detection
- [ ] `data_engine/circuit_detector.py`
- [ ] 5% / 10% / 20% circuit filter
- [ ] Auto-exit positions approaching circuit
- [ ] Block entry into stocks near circuit

---

## TIER 5 — Execution & Monitoring (Priority 19–24)

### P19: TWAP / VWAP Execution Algorithms
- [ ] `execution_engine/algos/twap.py`
- [ ] `execution_engine/algos/vwap_exec.py`
- [ ] Execution benchmark tracking

### P20: Transaction Cost Analysis (TCA)
- [ ] `analytics/tca.py`
- [ ] Actual fill vs expected price tracking
- [ ] Implementation shortfall per strategy
- [ ] Auto-switch to limit orders when slippage exceeds threshold

### P21: Live P&L Attribution
- [ ] `analytics/pnl_attribution.py`
- [ ] Per-strategy, per-symbol P&L breakdown
- [ ] Auto-disable strategy if rolling 30-day Sharpe < 0.5
- [ ] Auto-reduce size when drawdown > 50% of historical max

### P22: Telegram Alerts
- [ ] Full Telegram bot integration in `utils/notifier.py`
- [ ] Trade execution alerts (entry/exit with P&L)
- [ ] Daily P&L summary at 15:30 IST
- [ ] Risk breach alerts

### P23: Monte Carlo Backtesting
- [ ] `backtester/monte_carlo.py`
- [ ] 10,000 trade sequence randomizations
- [ ] Bootstrap Sharpe confidence intervals
- [ ] Path-dependent drawdown analysis

### P24: Bayesian Hyperparameter Optimization
- [ ] `optimization/bayesian_opt.py` using Optuna
- [ ] Weekly auto-tune via walk-forward
- [ ] Parameter sensitivity analysis
- [ ] Per-regime parameter sets

---

## Status Legend
- [ ] Not started
- [~] In progress
- [x] Complete
