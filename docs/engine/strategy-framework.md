# The Strategy Framework

Every trading idea in the engine is a **strategy**: a class that looks at a
price frame and either returns a `Signal` or nothing. The
`MetaStrategyEngine` runs all enabled strategies for a symbol, filters them by
market regime, and the caller picks the best signal by confidence × weight.

## Signals

`strategies/base.py`:

```python
@dataclass
class Signal:
    strategy: str          # name of the strategy that produced it
    symbol: str
    signal_type: SignalType   # BUY, SELL (CLOSE_LONG, CLOSE_SHORT, HOLD exist but are unused)
    price: float           # reference price, normally the last close
    stop_loss: float
    take_profit: float
    confidence: float      # 0–1
    timeframe: str = "1h"
    metadata: dict = {}    # strategy-specific details (pattern name, z-score, …)
    ts: str                # creation time, UTC ISO
```

`signal.direction` is +1 for BUY and −1 for SELL; `signal.is_entry` is true for
both.

## Writing a strategy

```python
class MyStrategy(BaseStrategy):
    name = "my_strategy"            # the key used in strategies.enabled / weights
    category = "momentum"
    preferred_regimes = ["trending"]   # or ["all"]

    def __init__(self, cfg):
        super().__init__(cfg)
        self.lookback = self.param("lookback", 20)        # strategies.params.my_strategy.lookback

    def generate_signal(self, df, symbol):
        if not self.validate_df(df, self.lookback + 5):   # enough bars?
            return None
        ...
        strength = self._unit(breakout_atrs)               # 0–1: how decisive the setup is
        sl, tp = self._atr_stops(df, direction=1)          # atr_stop_mult / atr_target_mult
        return Signal(strategy=self.name, symbol=symbol, signal_type=SignalType.BUY,
                      price=df["close"].iloc[-1], stop_loss=sl, take_profit=tp,
                      confidence=self.scaled_confidence(strength))

    def should_exit(self, df, direction, bars_held):       # optional
        base = super().should_exit(df, direction, bars_held)   # time stop
        if base:
            return base
        return "my exit rule" if ... else None
```

- `param(key, default)` — a tunable parameter (see below). The value is cast
  to the default's type and recorded in `self.params`, which the Strategies
  page shows.
- `validate_df(df, min_bars=50)` — enough data to compute indicators.
- `_atr_stops(df, direction)` — stop and target at `atr_stop_mult` /
  `atr_target_mult` ATR(14)s from the last close. The defaults come from the
  class attributes `default_atr_stop` / `default_atr_target` (2 and 3, a
  1 : 1.5 risk/reward); mean-reversion strategies set tighter ones.
- `scaled_confidence(strength, low=0.55, high=0.85)` — maps a 0–1 setup
  strength to a confidence. The engine ranks signals by confidence × weight,
  so a constant confidence would make the choice a fixed priority order.
  `_unit(x)` clamps to 0–1, and `_volume_ratio(df)` gives the last bar's
  volume over its 20-bar average.
- `should_exit(df, direction, bars_held)` — a strategy-specific exit (see
  [Strategy exits](#strategy-exits)).
- `self.weight` — the strategy's weight from config.

Then register the class in `_CORE_STRATEGIES` in `strategies/meta_engine.py`
(or `_try_import_extra_strategies` if it depends on an external data source
that can fail) and add a test.

### Where parameters come from

`param(key, default)` looks in this order:

1. `strategies.params.<strategy name>.<key>` in `config/settings.yaml`;
2. the legacy top-level key of the same name (for example `ema_fast: 12`),
   kept so older configs still work;
3. the default in code.

```yaml
strategies:
  params:
    donchian_breakout: {dc_period: 55, exit_period: 20, max_hold_bars: 30}
    rsi_momentum:      {rsi_period: 21, atr_stop_mult: 2.5}
```

Every strategy has `max_hold_bars` (time stop, 0 = off), `atr_stop_mult`
and `atr_target_mult`, plus its own keys. The Strategies page lists each
strategy's effective values (click a row), and `GET /api/config` returns
them under `params`. The data-dependent strategies (VIX, GIFT Nifty, FII/DII)
and the microstructure ones still read their own nested sections
(`volatility`, `gap`, `institutional`, `microstructure`).

### Strategy exits

Besides its stop and target, a position can be closed by the strategy that
opened it. On every closed bar the live bot calls
`should_exit(df, direction, bars_held)` on that strategy; a returned reason
closes the position as `strategy_exit (<reason>)`. The backtester does the
same, filling at that bar's close with reason `strategy_exit`.

| Strategy | Exit rule |
|---|---|
| All | Time stop after `max_hold_bars` bars (off by default) |
| `donchian_breakout` | Close through the opposite `exit_period`-bar channel (10) |
| `supertrend` | Supertrend flips against the position |
| `ema_crossover` | The opposite crossover |
| `rsi_momentum` | RSI back through 50 by `exit_buffer` (5) against the position |
| `zscore_reversion` | Z-score back within ±`zscore_exit` (0.5) of the mean |

## The MetaStrategyEngine

`strategies/meta_engine.py`:

```python
engine = MetaStrategyEngine(cfg)               # cfg = settings dict
signals = engine.generate_signals("RELIANCE", df)
best = engine.best_signal(signals)             # or None
```

**Construction** builds every registered strategy and keeps those listed in
`strategies.enabled` (all of them if the list is empty):

| Group | Strategies |
|---|---|
| Core (always built) | `ema_crossover`, `mtf_trend`, `supertrend`, `donchian_breakout`, `rsi_mean_reversion`, `bollinger_reversion`, `zscore_reversion`, `vwap_reversion`, `sr_breakout`, `breakout_atr`, `range_breakout`, `macd_momentum`, `rsi_momentum`, `volume_momentum`, `order_book_imbalance`, `anchored_vwap`, `cumulative_delta`, `volume_profile`, `candle_patterns` |
| Data-dependent (skipped if their import fails) | `vix_strategy`, `gift_nifty_gap`, `fii_dii` |
| ML | `ml_classifier` — loads `models/ensemble.pkl` if it exists |
| Side-car | `pair_trading` — always built, used through `generate_pair_signals()`, not the enabled list |

`registered_strategy_names()` returns all of these without building an engine.

**`generate_signals(symbol, df, extra_kwargs=None)`**:

1. Detects the market regime for the frame.
2. For each enabled strategy whose `preferred_regimes` match the regime (or is
   `["all"]`), calls `generate_signal(df, symbol)`, passing any of
   `extra_kwargs` the strategy's signature accepts (e.g. `frames=` for
   `mtf_trend`, `orderbook=` for `order_book_imbalance`).
3. A strategy that raises is logged and skipped.
4. Returns every non-empty signal.

**`best_signal(signals)`** returns the signal with the highest
`confidence × strategies.weights[name]` (default weight 1.0). The live bot,
paper trader, signal scanner, backtester and composite engine all rank this
way.

**`generate_pair_signals(df_map, pairs)`** runs pair trading over symbol pairs.

## Market regimes

`strategies/regime_detector.py` classifies a frame into one of five regimes:

| Regime | ADX/volatility rule |
|---|---|
| `HIGH_VOLATILITY` | 20-bar return volatility > `regime_detection.volatility_high_pct` (3 %) |
| `TRENDING_UP` / `TRENDING_DOWN` | ADX ≥ `adx_trend_threshold` (25); direction from price vs EMA(50) |
| `LOW_VOLATILITY` | volatility < 40 % of the high threshold |
| `RANGING` | everything else (and frames shorter than 25 bars) |

Strategy regime tags map onto these: `trending` (up or down), `trending_up`,
`trending_down`, `ranging`, `volatile` (high volatility), `low_volatility`,
`all`.

### The HMM detector

`strategies/hmm_regime.py` fits a six-state Gaussian Hidden Markov Model per
symbol on log returns, 5-bar volatility, volume ratio, ATR ratio and the share
of up-closes, maps states to regimes, and can report next-bar regime
probabilities. `RegimeDetector.detect()` uses it **only if a model has been
fitted and saved** for that symbol in `models/hmm/hmm_<SYMBOL>.pkl` (via
`RegimeDetector.fit_hmm(symbol, df)` or `HMMRegimeManager.fit_all()`).
Nothing in the bot or scripts fits these models today, so in practice the ADX
rules above are always used.

## Strategy catalogue

| Name | Chapter | Regimes | Enabled by default |
|---|---|---|---|
| `ema_crossover` | [Trend and Momentum](strategies-trend-momentum.md) | trending | no |
| `supertrend` | [Trend and Momentum](strategies-trend-momentum.md) | trending | no |
| `donchian_breakout` | [Trend and Momentum](strategies-trend-momentum.md) | trending | **yes** (1.2) |
| `mtf_trend` | [Trend and Momentum](strategies-trend-momentum.md) | trending | no |
| `macd_momentum` | [Trend and Momentum](strategies-trend-momentum.md) | trending | no |
| `rsi_momentum` | [Trend and Momentum](strategies-trend-momentum.md) | trending | **yes** (1.0) |
| `volume_momentum` | [Trend and Momentum](strategies-trend-momentum.md) | trending, volatile | **yes** (0.9) |
| `candle_patterns` | [Trend and Momentum](strategies-trend-momentum.md) | all | **yes** (0.7) |
| `rsi_mean_reversion` | [Mean Reversion and Breakout](strategies-mean-reversion-breakout.md) | ranging | no |
| `bollinger_reversion` | [Mean Reversion and Breakout](strategies-mean-reversion-breakout.md) | ranging | **yes** (1.2) |
| `zscore_reversion` | [Mean Reversion and Breakout](strategies-mean-reversion-breakout.md) | ranging | **yes** (1.0) |
| `vwap_reversion` | [Mean Reversion and Breakout](strategies-mean-reversion-breakout.md) | ranging, low volatility | **yes** (1.5) |
| `breakout_atr` | [Mean Reversion and Breakout](strategies-mean-reversion-breakout.md) | volatile | no |
| `range_breakout` | [Mean Reversion and Breakout](strategies-mean-reversion-breakout.md) | ranging, trending | no |
| `sr_breakout` | [Mean Reversion and Breakout](strategies-mean-reversion-breakout.md) | trending, volatile | no |
| `order_book_imbalance` | [Microstructure](strategies-microstructure.md) | all | no |
| `anchored_vwap` | [Microstructure](strategies-microstructure.md) | ranging, trending | **yes** (0.9) |
| `cumulative_delta` | [Microstructure](strategies-microstructure.md) | all | **yes** (0.8) |
| `volume_profile` | [Microstructure](strategies-microstructure.md) | all | **yes** (0.8) |
| `vix_strategy` | [Macro: VIX, GIFT Nifty, FII/DII](strategies-macro.md) | all | **yes** (1.1) |
| `gift_nifty_gap` | [Macro: VIX, GIFT Nifty, FII/DII](strategies-macro.md) | all | **yes** (1.0) |
| `fii_dii` | [Macro: VIX, GIFT Nifty, FII/DII](strategies-macro.md) | all | **yes** (0.8) |
| `pair_trading` | [Statistical Arbitrage](strategies-stat-arb.md) | side-car | — |
| `ml_classifier` | [Corporate Events and ML](strategies-corporate-ml.md) | all | no |
| Options (5) | [Options Strategies](strategies-options.md) | — | not wired |
| `pead` | [Corporate Events and ML](strategies-corporate-ml.md) | — | not wired |

The default `enabled` list and weights in `config/settings.yaml` were chosen
from a two-year daily backtest on six large caps. Several results behind those
choices predate later fixes — notably `vwap_reversion` and `anchored_vwap`,
which no longer trade on daily bars (see their chapters). Re-run
`scripts/tune_weights.py` before relying on the shipped weights.
