# Strategies Reference

All 25+ strategies implemented. Each entry covers: what it does, key parameters,
entry/exit logic, and which market regime it works best in.

---

## How Strategies Are Orchestrated

All strategies feed signals into `MetaStrategyEngine` (`strategies/meta_engine.py`):

1. **Regime detection** — HMM (6-state) + ADX + volatility determines current regime
2. **Strategy filtering** — wrong-regime strategies are silenced (e.g. mean-reversion is
   suppressed in a strong trend)
3. **Signal blending** — surviving signals are weighted and combined into a final signal
4. **Risk gate** — position sizer validates against portfolio limits before execution

```python
from strategies.meta_engine import MetaStrategyEngine
engine = MetaStrategyEngine(config=settings)
signal = engine.generate_signal(df, symbol="RELIANCE")
# signal.type: BUY | SELL | HOLD
# signal.strength: 0.0 – 1.0
# signal.strategy: "ema_crossover" (primary contributor)
```

---

## Regime Detection

### ADX Regime Detector (`strategies/regime_detector.py`)

| Regime | Condition | Active strategies |
|---|---|---|
| Trending | ADX > 25, directional | Trend, breakout, momentum |
| Strong trend | ADX > 40 | Trend only |
| Ranging | ADX < 25, low vol | Mean reversion, stat arb |
| Volatile | Daily vol > 3% | VIX strategy, reduced size |

### HMM Regime Detector (`strategies/hmm_regime.py`)

6-state Gaussian Hidden Markov Model trained on (returns, vol, volume) features:
- States typically map to: bull quiet, bull momentum, bear quiet, bear panic, sideways tight, sideways choppy
- `predict_next_regime_probs()` uses forward propagation through transition matrix for 1-step ahead probabilities

```python
from strategies.hmm_regime import HMMRegimeDetector
hmm = HMMRegimeDetector(symbol="NIFTY50")
hmm.fit(df)
regime = hmm.predict(df)              # current state index
probs  = hmm.predict_next_regime_probs(df)   # {0: 0.32, 1: 0.41, ...}
```

---

## Trend Strategies

### EMA Crossover (`strategies/trend/ema_crossover.py`)

Classic fast/slow EMA crossover with volume confirmation.
- **Entry:** EMA9 crosses above EMA20 (BUY) or below (SELL), volume > 1.2× average
- **Filter:** Only trades when EMA20 > EMA50 (uptrend structure)
- **Best regime:** Trending
- **Weight in ensemble:** 1.0

### Supertrend (`strategies/trend/supertrend.py`)

ATR-based dynamic support/resistance line.
- **Entry:** Price crosses from below to above Supertrend line (BUY)
- **Exit:** Price crosses back below Supertrend line (trailing)
- **Parameters:** `atr_period=10`, `multiplier=3.0`
- **Best regime:** Trending, moderate volatility

### Donchian Breakout (`strategies/trend/donchian_breakout.py`)

N-period high/low channel breakout (Turtle Trading variant).
- **Entry:** Price breaks above 20-day high (BUY) or below 20-day low (SELL)
- **Exit:** Price crosses the 10-day channel midline
- **Best regime:** Trending, breakout setups

### Multi-Timeframe Trend (`strategies/trend/multi_timeframe_trend.py`)

Requires trend alignment across daily, hourly, and 15-min timeframes.
- **Entry:** All three timeframes show same direction (EMA slope + ADX confirmation)
- **Strongest signal:** score = 3/3 (all aligned)
- **Best regime:** Strong trending

---

## Mean Reversion Strategies

### RSI Reversion (`strategies/mean_reversion/rsi_reversion.py`)

- **Entry BUY:** RSI(14) < 30 (oversold) + price at lower Bollinger band
- **Entry SELL:** RSI(14) > 70 (overbought) + price at upper Bollinger band
- **Exit:** RSI crosses back to 50
- **Best regime:** Ranging, low ADX

### Bollinger Band Reversion (`strategies/mean_reversion/bollinger_reversion.py`)

- **Entry:** Price touches ±2σ band with RSI divergence
- **Target:** Band midline (20-period SMA)
- **Stop:** Beyond the ±2.5σ band
- **Best regime:** Ranging

### Z-Score Reversion (`strategies/mean_reversion/zscore_reversion.py`)

- **Entry:** 20-day z-score > 2.0 (overbought) or < -2.0 (oversold)
- **Exit:** Z-score returns to 0 ± 0.5
- **Best regime:** Ranging, mean-reverting tickers

### VWAP Reversion (`strategies/mean_reversion/vwap_reversion.py`)

Intraday strategy — trades reversion to session VWAP.
- **Entry BUY:** Price > 1.5% below VWAP + RSI < 40
- **Entry SELL:** Price > 1.5% above VWAP + RSI > 60
- **Exit:** Price returns to VWAP ± 0.3%
- **Best regime:** Intraday ranging sessions

---

## Breakout Strategies

### ATR Breakout (`strategies/breakout/atr_breakout.py`)

Volatility-contraction breakout (Bollinger squeeze → expansion).
- **Entry:** Bandwidth at 20-day low (squeeze) then price breaks above/below recent high/low
- **Target:** Entry ± 2×ATR
- **Stop:** Entry ∓ 1×ATR
- **Best regime:** Transition from low-vol to high-vol

### Range Breakout (`strategies/breakout/range_breakout.py`)

Opening Range Breakout (ORB) for intraday:
- **Range:** First 30 minutes of NSE session (09:15–09:45)
- **Entry:** Price breaks above range high (BUY) or below range low (SELL)
- **Exit:** End of day or target = 2× range size
- **Best regime:** Gap-up/gap-down mornings

### Support/Resistance Breakout (`strategies/breakout/support_resistance.py`)

Key S/R levels from pivot points and volume profile POC.
- **Entry:** Clean break with volume > 1.5× average
- **Confirmation:** 15-min close beyond level
- **Best regime:** Trending after consolidation

---

## Momentum Strategies

### MACD Momentum (`strategies/momentum/macd_momentum.py`)

- **Entry BUY:** MACD histogram turns positive + histogram slope accelerating
- **Entry SELL:** MACD histogram turns negative + accelerating down
- **Filter:** Only trade if ADX > 20
- **Best regime:** Trending

### RSI Momentum (`strategies/momentum/rsi_momentum.py`)

- **Entry BUY:** RSI crosses above 50 from below (momentum confirmation)
- **Entry SELL:** RSI crosses below 50 from above
- **Best regime:** Trending (opposite to RSI Reversion — ensure regime filter is active)

### Volume Momentum (`strategies/momentum/volume_momentum.py`)

- **Entry:** Volume ratio (today/10-day avg) > 2.0 + price direction
- **Thesis:** Unusual volume precedes sustained moves
- **Best regime:** Trending

---

## Microstructure Strategies

### Order Book Imbalance (`strategies/microstructure/order_book_imbalance.py`)

- **Entry BUY:** Bid volume / (bid + ask volume) > 0.65 (strong buying pressure)
- **Entry SELL:** Ratio < 0.35 (strong selling pressure)
- **Whale detection:** Single order > 5× average order size in top 5 levels
- **Weight in ensemble:** 0.5 (noisier signal)

### Anchored VWAP (`strategies/microstructure/anchored_vwap.py`)

Session-VWAP with ±1σ and ±2σ bands.
- **Support:** Price near VWAP after pullback → BUY
- **Resistance:** Price near VWAP after rally → SELL
- **±2σ bands:** Extreme mean-reversion entries

```python
from strategies.microstructure.anchored_vwap import compute_anchored_vwap
vwap, upper2, upper1, lower1, lower2 = compute_anchored_vwap(df)
```

### Cumulative Delta (`strategies/microstructure/cumulative_delta.py`)

Tracks net buy vs sell volume (estimated from bar close position):
- **Divergence signal:** Price makes new high but cumulative delta declining → distribution
- **Confirmation:** Price and delta moving together → momentum continuation

```python
from strategies.microstructure.cumulative_delta import DeltaTracker
tracker = DeltaTracker()
for _, row in df.iterrows():
    tracker.add_bar(row)
summary = tracker.summary()
# {'cumulative_delta': 1234.0, 'total_buy_volume': 56000, 'buy_sell_ratio': 1.35, ...}
```

### Volume Profile (`strategies/microstructure/volume_profile.py`)

Daily session volume profile with POC / VAH / VAL:
- **POC (Point of Control):** Price with highest volume — acts as magnet
- **VAH / VAL:** Value Area High/Low (70% of volume) — support/resistance

```python
from strategies.microstructure.volume_profile import compute_volume_profile
vp = compute_volume_profile(df, bins=20)
# vp.poc, vp.vah, vp.val, vp.value_area_pct
```

---

## Statistical Arbitrage

### Pair Trading (`strategies/stat_arb/pair_trading.py`)

Cointegration-based long/short pairs with Kalman hedge ratio.

1. **Cointegration test:** ADF test on spread, p-value < 0.05
2. **Kalman hedge ratio:** Dynamic β via Kalman filter (adapts to regime shifts)
3. **Z-score:** Standardised spread over rolling window
4. **Entry:** |z| > `entry_z` (default 2.0) — long underpriced, short overpriced
5. **Exit:** |z| < `exit_z` (default 0.5)
6. **Uncertainty penalty:** Reduces signal confidence when Kalman variance is high

```python
from strategies.stat_arb.pair_trading import PairTradingStrategy
strategy = PairTradingStrategy(cfg={})
signal_a, signal_b = strategy.generate_pair_signals(df_a, df_b, symbol_a, symbol_b)
```

### Kalman Hedge Ratio (`utils/kalman.py`)

Dynamic hedge ratio tracking (outperforms rolling OLS for non-stationary spreads):
```python
from utils.kalman import KalmanHedgeRatio
kf = KalmanHedgeRatio()
kf.update(price_a, price_b)
beta = kf.beta            # current hedge ratio
uncertainty = kf.variance # Kalman filter uncertainty (P[0,0])
```

---

## Volatility Strategy

### India VIX Strategy (`strategies/volatility/vix_strategy.py`)

Three sub-modes triggered by VIX levels:

| VIX Level | Classification | Action |
|---|---|---|
| < 12 | Complacency | Buy protective puts |
| 12–17 | Normal | No VIX signal |
| 17–21 | Elevated | Reduce equity exposure |
| 21–27 | High fear | Start accumulating — fear extreme |
| 27–35 | Extreme fear | Strong BUY signal (contrarian) |
| > 35 | Panic | Maximum accumulation |

**VIX spike reversal:** When VIX spikes > `spike_threshold`% in one day and
Nifty drops > `nifty_drop_pct`%, enter long with `hold_days` exit.

```python
from strategies.volatility.vix_strategy import VixStrategy
vix_strat = VixStrategy(cfg={})
signal = vix_strat.generate_signal(df_nifty, current_vix=22.5)
```

---

## Options Strategies

### Gamma Scalping (`strategies/options/gamma_scalping.py`)

Long gamma position (straddle) delta-hedged continuously.
- **Entry:** Low IV environment (IV rank < 30th percentile)
- **P&L source:** Gamma gains from large moves exceed theta decay
- **Delta hedge:** Re-hedge when delta drifts beyond ±0.1

### Iron Condor (`strategies/options/iron_condor.py`)

Sell OTM call spread + OTM put spread (range-bound thesis).
- **Entry:** IV rank > 70th percentile (expensive premium → sell)
- **Strikes:** ATM ± 1σ for short strikes, ATM ± 2σ for long strikes (defined risk)
- **Max profit:** Full credit received
- **Max loss:** Spread width minus credit

### Theta Decay (`strategies/options/theta_decay.py`)

Short OTM options harvesting time decay.
- **Entry:** High IV environment, 20–45 DTE
- **Exit:** 50% of max profit or 21 DTE
- **Risk filter:** VIX < 25 (avoid short gamma in panic)

### Straddle / Strangle (`strategies/options/straddle_strangle.py`)

Long volatility — profit from large moves in either direction.
- **Entry:** IV rank < 20th percentile (cheap premium → buy)
- **Straddle:** ATM call + ATM put
- **Strangle:** OTM call + OTM put (cheaper, needs bigger move)

### BankNifty Expiry Day (`strategies/options/expiry_strategy.py`)

Three sub-strategies for BankNifty weekly expiry (0DTE):

| Sub-strategy | Logic |
|---|---|
| Max Pain Pinning | Sell ATM straddle if spot within ±0.5% of max pain, IV < 30% |
| Gamma Squeeze | Buy ATM options if large OI exists at nearby strike (gamma risk) |
| Morning Reversal | Fade the opening gap if gap > 0.3% within first 30 min |

Key constraints:
- Mandatory exit by **15:15 IST** (SEBI auto-squareoff window)
- Max 1% of capital per trade
- Skip if ATM IV > 30% (too expensive)

---

## Institutional Flow Strategy

### FII/DII Flow (`strategies/institutional/fii_dii_strategy.py`)

- FII net buy > ₹500 Cr for 3 consecutive days → BUY signal
- FII net sell > ₹500 Cr for 3 consecutive days → SELL signal
- DII buying against FII selling → mixed/neutral signal
- Data source: NSE daily FII/DII press release (scraped automatically)

---

## Gap Strategy

### GIFT Nifty Gap (`strategies/gap/gift_nifty_gap.py`)

Pre-market strategy using GIFT Nifty (trades 23:30 IST to next day 15:30 IST).

| Gap size | Action |
|---|---|
| > +0.5% | Strong gap up → sell at open (gap fill probability > 60%) |
| +0.2% to +0.5% | Weak gap up → wait for confirmation |
| -0.2% to +0.2% | Flat → no gap trade |
| -0.2% to -0.5% | Weak gap down → wait |
| < -0.5% | Strong gap down → buy at open (gap fill) |

---

## Corporate Action Strategy

### PEAD — Post-Earnings Announcement Drift (`strategies/corporate/pead_strategy.py`)

Exploits the well-documented drift following earnings surprises.

**Earnings Surprise Score (ESS):**
```
ESS = (actual_EPS - consensus_EPS) / |consensus_EPS| × 100
```

| ESS | Action |
|---|---|
| > +5% | Buy — positive surprise, expect drift up for 20–30 days |
| < -5% | Sell / avoid — negative surprise, expect drift down |
| -5% to +5% | No trade |

Filters:
- F&O ban check (cannot short if stock is in ban)
- Liquidity check: avg volume > 100K shares/day
- Stop loss: 5% below entry
- Target: 12% above entry
- Exit: 30 days after entry (drift window closes)

---

## ML-Based Strategy

### ML Classifier Strategy (`strategies/ml_based/ml_strategy.py`)

Wrapper that runs the full ML ensemble (XGBoost + LightGBM + LSTM) and converts
probability output to a trading signal:

| P(buy) | Signal |
|---|---|
| > 0.60 | BUY, strength = P(buy) |
| < 0.40 | SELL, strength = P(sell) |
| 0.40–0.60 | HOLD |

Weight in ensemble: 1.2 (slightly upweighted vs rule-based strategies).

---

## Strategy Weights in Meta Engine

From `config/settings.yaml`:

| Strategy | Weight |
|---|---|
| ema_crossover | 1.0 |
| rsi_mean_reversion | 1.0 |
| bollinger_reversion | 1.0 |
| breakout_atr | 1.0 |
| macd_momentum | 1.0 |
| order_book_imbalance | 0.5 |
| pair_trading | 0.8 |
| ml_classifier | 1.2 |

To add or reweight strategies, edit `strategies.weights` in `config/settings.yaml`.
