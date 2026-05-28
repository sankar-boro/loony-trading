# Loony Trading — Implementation Todo

Full audit of missing, incomplete, or broken components.
Items are ordered by priority. Check off as completed.

---

## 🔴 Critical

- [x] **Docker stale — Streamlit refs everywhere** (`Dockerfile`, `docker-compose.yml`)
  - Exposes port 8501 instead of 8000; runs `streamlit run` instead of FastAPI+React
  - docker-compose missing all Upstox env vars; healthcheck trivial

- [x] **`requirements.txt` wrong** — `streamlit` still listed; `yfinance` missing; `tensorflow` not optional

- [x] **Scripts ignore `settings.yaml`** — `paper_trade.py`, `live_signals.py`, `backtest_runner.py` all
  build their own empty cfg dict; enabled list and weights from settings.yaml never applied

- [x] **NSE 2025/2026 holidays missing** — `india_market.holidays: []`; market-open check wrong on 17 holidays/year

---

## 🟠 Major

- [x] **`advanced_features.py` not wired into `FeatureBuilder`** — cross-asset, FII/DII momentum,
  PCR, delivery ratio, VIX features exist but never called; ML trains on basic TA only

- [x] **3 microstructure strategies not in engine** — `AnchoredVWAPStrategy`, `CumulativeDeltaStrategy`,
  `VolumeProfileStrategy` implemented but missing from `MetaStrategyEngine`

- [x] **HMM regime detector not connected** — `strategies/hmm_regime.py` exists but
  `RegimeDetector` uses only ADX+volatility rules

- [x] **`loony.sh` calls `check_token.py --quiet`** — flag doesn't exist; status command errors

- [x] **Add `GET /api/health` endpoint** — `scripts/health.py` is CLI only; no HTTP health check

- [x] **Add `.env.example`** — no template; new users must reverse-engineer required vars

- [x] **`dashboard/app.py` dead code** — old Streamlit app still exists; confusing alongside FastAPI

- [x] **`run_dev.sh` / `run_prod.sh` duplicated by `start.sh`/`stop.sh`** — remove old scripts

---

- [x] **Stock universe too small** — only 12 hardcoded stocks across all scripts and dashboard;
  replaced with `config/instruments.py` (91 stocks, 18 sectors, F&O flags, ISINs);
  all scripts import from central registry; watchlist expanded to 30 stocks;
  `/api/universe` endpoint added; Dashboard watchlist panel shows sector tabs + search

---

## 🟡 Medium

- [ ] **Re-train ML with full dataset** — last run used 2 symbols × 365 days (396 samples);
  run `python scripts/train_ml.py --days 730` for proper 6-symbol 2-year model

- [ ] **Backtester warmup inconsistency** — scripts use `warmup_bars: 50`; settings.yaml has `200`;
  `tune_weights.py` also uses `50`; all should read from config

- [ ] **Upstox token expiry logic wrong** — tokens expire at midnight IST, not 23h from issuance;
  `check_token.py` and `health.py` use age-from-file which can show "valid" when already expired

- [ ] **Corporate actions not applied to historical prices** — `corporate_actions.py` exists but
  never called from `FeatureBuilder` or `UpstoxDataEngine`; splits/bonuses cause price jumps

- [ ] **`PEADStrategy` wired to nothing** — needs earnings surprise data source; either connect
  NSE announcements feed or document as requiring manual injection

- [ ] **Options strategies need separate paper trading mode** — 4 options strategies require
  live IV surface + multi-leg P&L tracking; incompatible with current single-leg paper trader

- [ ] **`seed_dashboard_data.py` uses old strategy name `candlestick_pattern`** — should be
  `candle_patterns`; seed data in `logs/paper_trades.jsonl` has wrong strategy label

- [ ] **ML classifier not in `settings.yaml` enabled list** — after training, user must manually
  add `ml_classifier` to enabled; train script should update settings automatically

---

## 🔵 Low / Polish

- [ ] **`docker-compose.yml` healthcheck trivial** — always passes; should hit `/api/health`

- [ ] **`requirements.txt` no dev/prod split** — `tensorflow`, `pytest`, `stable-baselines3`
  should be in `requirements-dev.txt` or marked optional

- [ ] **`advanced_features.py` uses `yfinance` for cross-asset** — not in requirements; blocked
  in some environments; add fallback or make optional

- [ ] **No test for ML model training pipeline** — `tests/` has no coverage for
  `ModelTrainer`, `EnsembleModel`, or `train_ml.py`

- [ ] **`strategies/hmm_regime.py` tests missing** — HMM regime detection untested

- [ ] **Dashboard Chart page: no live price overlay** — static candles only; no real-time last-price
  line during market hours

- [ ] **Dashboard: no order initiation UI** — paper trades can only be started from CLI;
  no way to trigger a paper order from the dashboard

- [ ] **`loony.sh status` hardcoded port 8000** — doesn't work if user started prod server on custom port

- [ ] **`factor_model.py` incomplete** — analytics/factor_model.py exists (231L) but factor
  exposures not surfaced anywhere in dashboard or reports

- [ ] **`beta_neutral.py` not connected** — portfolio_manager/beta_neutral.py has beta hedging
  logic but PortfolioManager never calls it

- [ ] **Regime detector only 4 regimes** — TRENDING_UP/DOWN, RANGING, HIGH/LOW_VOLATILITY;
  HMM could add BREAKOUT, MEAN_REVERTING, CRISIS regimes

---

## Strategy Status

| Strategy | Category | In Engine | Status |
|---|---|---|---|
| `ema_crossover` | trend | ✓ | Complete |
| `supertrend` | trend | ✓ | Complete |
| `donchian_breakout` | trend | ✓ | Complete |
| `multi_tf_trend` | trend | ✓ | Needs multi-TF frames to fire |
| `rsi_mean_reversion` | mean_reversion | ✓ | Complete |
| `bollinger_reversion` | mean_reversion | ✓ | Complete |
| `zscore_reversion` | mean_reversion | ✓ | Complete |
| `vwap_reversion` | mean_reversion | ✓ | Complete |
| `sr_breakout` | breakout | ✓ | Complete |
| `breakout_atr` | breakout | ✓ | Complete |
| `range_breakout` | breakout | ✓ | Complete |
| `macd_momentum` | momentum | ✓ | Complete |
| `rsi_momentum` | momentum | ✓ | Complete |
| `volume_momentum` | momentum | ✓ | Complete |
| `order_book_imbalance` | microstructure | ✓ | Complete |
| `candle_patterns` | price_action | ✓ | Complete |
| `vix_strategy` | volatility | ✓ | Complete — fires NIFTY/BANKNIFTY only |
| `gift_nifty_gap` | gap | ✓ | Complete — fires at market open only |
| `fii_dii` | institutional | ✓ | Complete — fires NIFTY/BANKNIFTY only |
| `ml_classifier` | ml | ✓ | Needs model trained (`train_ml.py`) |
| `pair_trading` | stat_arb | side-car | Complete |
| `anchored_vwap` | microstructure | ✗ | **To wire in** |
| `cumulative_delta` | microstructure | ✗ | **To wire in** |
| `volume_profile` | microstructure | ✗ | **To wire in** |
| `iron_condor` | options | ✗ | Needs live IV surface |
| `gamma_scalping` | options | ✗ | Needs live IV surface |
| `straddle_strangle` | options | ✗ | `generate_signal()` returns None |
| `theta_decay` | options | ✗ | Needs live IV surface |
| `pead` | corporate | ✗ | Needs earnings data feed |
| `fii_dii_delivery` | institutional | ✗ | Stock-level delivery signal, not wired |
