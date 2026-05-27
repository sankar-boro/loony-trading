# P2 — Important (Trading Incorrectly / Silent P&L Errors)

These gaps mean the bot is running but producing wrong signals, wrong position sizes,
or wrong P&L numbers — without any visible error.

---

## P2-1 · Corporate Action Adjustments (Bonus / Split / Dividend)

**Status:** ❌ Missing  
**Risk:** Unadjusted price history causes massive false signals. A 1:1 bonus makes the price halve overnight — the backtester treats it as a 50% crash and fires a SELL signal that never should have triggered.

### Problem

Upstox `/historical-candle/` returns **unadjusted** prices by default.
When any of these events occur, the price series has a discontinuity:

| Corporate Action | Price Effect | Signal Corruption |
|-----------------|-------------|------------------|
| 1:1 Bonus share | Price halves | False crash signal |
| 10:1 Stock split | Price drops 90% | Triggers SL on every strategy |
| ₹10 dividend | Price drops by ₹10 | False mean-reversion entry |
| Rights issue | Price drops | Similar to dividend |

Recent examples that affect the default watchlist:
- RELIANCE: multiple bonus issues in history
- TCS: 1:1 bonus in 2018
- HDFCBANK: merger with HDFC Ltd in 2023 (price restructuring)

### What needs to be built

**Option A (Recommended): Use Upstox adjusted prices**

Check if Upstox API supports an `adjusted=true` parameter or a separate adjusted endpoint:
```python
# Try adding to fetch in upstox_data.py:
url = f"/historical-candle/{key}/{interval}/{to_d}/{from_d}?adjusted=true"
```
As of 2025, Upstox does not expose an explicit adjusted flag — verify in their docs.

**Option B: NSE corporate actions feed**

NSE publishes a corporate actions CSV at:
```
https://www.nseindia.com/api/corporates-corporateActions?index=equities
```
Fetch this on startup (or daily), build an adjustment factor per symbol, and multiply historical prices:
```python
def apply_adjustments(df: pd.DataFrame, symbol: str, actions: list[dict]) -> pd.DataFrame:
    """
    Multiply all OHLCV prices before an action date by the adjustment factor.
    For a 1:1 bonus: factor = 0.5 for all dates before bonus date.
    For a 2:1 split: factor = 0.5 for all dates before split date.
    """
    df = df.copy()
    for action in sorted(actions, key=lambda x: x["date"], reverse=True):
        ex_date = pd.Timestamp(action["date"])
        factor = action["factor"]   # e.g. 0.5 for 1:1 bonus
        mask = df.index < ex_date
        for col in ["open", "high", "low", "close"]:
            df.loc[mask, col] *= factor
    return df
```

**`data_engine/upstox/upstox_data.py`** — call `apply_adjustments()` inside `fetch_ohlcv()` before returning.

**`data/corporate_actions.json`** — cached copy, refreshed daily at midnight.

### Files to change
- Create `data_engine/upstox/corporate_actions.py` → fetch + cache NSE actions
- Edit `data_engine/upstox/upstox_data.py` → apply adjustments in `fetch_ohlcv()`
- Edit `scripts/backtest_runner.py` → use adjusted data fetch
- Edit `scripts/live_signals.py` → use adjusted data fetch

### Acceptance criteria
- [ ] RELIANCE daily chart shows no spurious price discontinuities
- [ ] Backtester results are stable across known bonus/split dates
- [ ] Corporate actions data is cached to avoid fetching on every run

---

## P2-2 · Transaction Cost Accuracy

**Status:** ⚠️ Incorrect  
**Risk:** Backtests show wrong P&L. Overcounting costs makes profitable strategies look losers. Undercounting makes losing strategies look profitable.

### Problem

Current model in `execution_engine/upstox_executor.py`:
```python
self._brokerage_pct = 0.0003   # 0.03%
stt = fill_price * order.quantity * 0.001 if order.transaction_type == "SELL" else 0
```

**Actual NSE costs (2025):**

#### Intraday (MIS) round-trip:
| Charge | Rate | Direction |
|--------|------|-----------|
| Brokerage (Zerodha/Upstox flat) | ₹20 per order OR 0.03%, whichever is lower | Both |
| STT | 0.025% | Sell side only |
| NSE exchange transaction charge | 0.00345% | Both |
| GST on brokerage+exchange charge | 18% | Both |
| SEBI turnover fee | ₹10 per crore (0.0001%) | Both |
| Stamp duty | 0.003% | Buy side only |
| **Total per round-trip** | **~0.055%** | — |

#### Delivery (CNC) round-trip:
| Charge | Rate | Direction |
|--------|------|-----------|
| Brokerage | 0 (Zerodha/Upstox: free) | — |
| STT | 0.1% | Both sides |
| NSE exchange charge | 0.00345% | Both |
| GST | 18% on exchange charge | Both |
| SEBI fee | 0.0001% | Both |
| Stamp duty | 0.015% | Buy side only |
| **Total per round-trip** | **~0.21%** | — |

### What needs to be built

**`execution_engine/upstox_executor.py`** — replace `_paper_fill()` cost calculation:
```python
def _compute_charges(self, price: float, qty: int, side: str, product: str) -> float:
    value = price * qty
    
    if product == "CNC":
        brokerage = 0.0       # Upstox delivery is free
        stt = value * 0.001   # 0.1% on both sides
    else:  # MIS / NRML intraday
        brokerage = min(20.0, value * 0.0003)  # ₹20 flat or 0.03%
        stt = value * 0.00025 if side == "SELL" else 0.0

    exchange_charge = value * 0.0000345
    gst = (brokerage + exchange_charge) * 0.18
    sebi_fee = value * 0.000001
    stamp_duty = value * 0.00003 if side == "BUY" else 0.0

    return brokerage + stt + exchange_charge + gst + sebi_fee + stamp_duty
```

Also add to `backtester/backtester.py` — the backtester uses `commission_pct` from config:
```yaml
# config/settings.yaml
execution:
  commission_intraday: 0.00055   # MIS round-trip ~0.055%
  commission_delivery: 0.0021    # CNC round-trip ~0.21%
  slippage_pct: 0.0005           # 0.05% market impact
```

### Files to change
- Edit `execution_engine/upstox_executor.py` → replace `_paper_fill()` cost logic
- Edit `backtester/backtester.py` → use separate intraday/delivery commission
- Edit `config/settings.yaml` → add correct commission constants

### Acceptance criteria
- [ ] Intraday round-trip cost ≈ 0.055% of trade value
- [ ] Delivery round-trip cost ≈ 0.21% of trade value
- [ ] `backtest_runner.py` output shows "Charges" line per trade
- [ ] Existing passing tests still pass after cost fix

---

## P2-3 · ML Models Not Trained

**Status:** ❌ No model files exist  
**Risk:** `MLClassifierStrategy` is enabled by default in `MetaStrategyEngine`. It silently fails on every signal generation call because no model files exist in `models/`. This means every run of `live_signals.py` and `paper_trade.py` is missing one strategy.

### Problem

Directory `models/` only contains:
```
models/hmm/   ← HMM regime models (trained on the fly)
```

Missing:
```
models/RELIANCE_xgb.pkl
models/RELIANCE_lgbm.pkl
models/RELIANCE_ensemble.pkl
models/TCS_xgb.pkl
... etc
```

`MLClassifierStrategy.generate_signal()` calls `self.model.predict(X)` which returns `None` when no model is loaded, effectively making the strategy a no-op.

### What needs to be done

**Step 1: Run the training pipeline**
```bash
# Train models for the default watchlist (RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK)
python main.py --mode train
```
This calls `ModelTrainer.train_all()` which:
1. Fetches 365 days OHLCV from Upstox for each symbol
2. Builds features with `FeatureBuilder`
3. Trains XGBoost + LightGBM with time-series cross-validation
4. Creates ensemble and saves to `models/{SYMBOL}_ensemble.pkl`

**Step 2: Verify models loaded**
```bash
python -c "
from ml_models.ensemble import EnsembleModel
m = EnsembleModel()
m.load('models/RELIANCE_ensemble.pkl')
print('RELIANCE model loaded:', m.is_trained)
"
```

**Step 3: Add model existence check to bot startup**
In `main.py` or `scripts/live_signals.py`:
```python
missing_models = []
for sym in watchlist:
    model_path = ROOT / "models" / f"{sym}_ensemble.pkl"
    if not model_path.exists():
        missing_models.append(sym)

if missing_models:
    print(f"WARNING: No ML models for: {', '.join(missing_models)}")
    print("Run: python main.py --mode train")
    print("ML strategy will be skipped for these symbols.")
```

**Step 4: Automated weekly retraining**
Add to crontab (Sunday 6 AM IST = Saturday 00:30 UTC):
```
30 0 * * 0 cd /path/to/loony-trading && python main.py --mode train >> logs/retrain.log 2>&1
```

### Files to change
- Run `python main.py --mode train` to generate initial models
- Edit `main.py` → add model existence warning on startup
- Edit `scripts/live_signals.py` → add model existence check
- Add weekly retrain cron entry

### Acceptance criteria
- [ ] `models/RELIANCE_ensemble.pkl` and similar files exist
- [ ] `live_signals.py` shows ML strategy signals for trained symbols
- [ ] Missing model generates a warning, not a silent skip
- [ ] Weekly retrain cron is documented

---

## P2-4 · Intraday Data Goes Stale During Session

**Status:** ⚠️ Partial  
**Risk:** When using 1h or 15m timeframes, historical data is loaded at startup (e.g., 8:50 AM). By 11 AM, several new candles have formed but the strategy is still seeing the pre-open snapshot. Signals are 2+ hours stale.

### Problem

In `paper_trade.py`:
```python
# Loaded once at 8:50 AM
hist_data[sym] = _fetch_ohlcv(token, ikey, interval, days)
```

Then every tick:
```python
ltp = prices.get(ikey, 0.0)
df.at[last_ts, "close"] = ltp  # only updates the LAST daily bar's close
```

For a **daily** timeframe this is acceptable — there's only one candle per day.
For a **1h timeframe**: after 9:15 AM, new hourly candles form at 10:15, 11:15, 12:15, etc. These never get appended. The strategy at 2 PM is still seeing the last candle from yesterday's close.

### What needs to be built

**`scripts/paper_trade.py`** — add a data refresh function:
```python
def _refresh_intraday(token: str, sym: str, ikey: str,
                      interval: str, df_old: pd.DataFrame,
                      fb) -> pd.DataFrame:
    """
    Fetch the latest intraday candles and append any new ones to df_old.
    Called every candle period (e.g., every 60 min for 1h data).
    """
    if interval == "day":
        return df_old   # daily data only needs LTP update, not new candles
    
    # Fetch last 2 days of intraday to catch today's candles
    df_new = _fetch_ohlcv(token, ikey, interval, days=2)
    if df_new.empty:
        return df_old
    
    # Merge: keep old candles + add any new ones not already in df_old
    df_combined = pd.concat([df_old, df_new])
    df_combined = df_combined[~df_combined.index.duplicated(keep="last")]
    df_combined = df_combined.sort_index()
    
    if fb is not None:
        try:
            df_combined = fb.build(df_combined)
        except Exception:
            pass
    return df_combined
```

**Refresh schedule**: re-fetch once per candle period.
- 1h timeframe → refresh every 60 minutes
- 15m timeframe → refresh every 15 minutes
- 30m timeframe → refresh every 30 minutes

```python
# Track last refresh time
_last_refresh: dict[str, float] = {}
candle_seconds = {"day": 86400, "60minute": 3600, "30minute": 1800, "15minute": 900}

for sym, ikey in resolved:
    period = candle_seconds.get(interval, 3600)
    if time.time() - _last_refresh.get(sym, 0) > period:
        hist_data[sym] = _refresh_intraday(token, sym, ikey, interval,
                                            hist_data[sym], fb)
        _last_refresh[sym] = time.time()
```

### Files to change
- Edit `scripts/paper_trade.py` → add `_refresh_intraday()` and call on schedule
- Edit `scripts/live_signals.py` → same refresh for `--refresh` mode with intraday TF

### Acceptance criteria
- [ ] `--timeframe 1h` in `paper_trade.py` shows new candles appearing every hour
- [ ] Refreshed data includes today's partial candle
- [ ] Daily timeframe is unaffected (no unnecessary extra API calls)

---

## P2-5 · Options Multi-Leg Execution Missing

**Status:** ❌ Missing  
**Risk:** Five options strategies (gamma scalping, theta decay, iron condor, straddle, expiry) generate signals but cannot be executed. The execution engine only supports single-leg equity orders.

### Problem

Options strategies in `strategies/options/` generate signals with metadata like:
```python
Signal(
    strategy="iron_condor",
    symbol="NIFTY",
    signal_type=SignalType.BUY,
    metadata={
        "legs": [
            {"action": "SELL", "type": "CE", "strike": 24500, "expiry": "2025-06-26"},
            {"action": "BUY",  "type": "CE", "strike": 24700, "expiry": "2025-06-26"},
            {"action": "SELL", "type": "PE", "strike": 23500, "expiry": "2025-06-26"},
            {"action": "BUY",  "type": "PE", "strike": 23300, "expiry": "2025-06-26"},
        ]
    }
)
```

But `UpstoxExecutor.execute_signal()` only handles `signal.symbol` as a single instrument key. The `legs` metadata is ignored.

### What needs to be built

**1. Options instrument resolution**

F&O instrument keys follow the pattern:
```
NSE_FO|NIFTY25JUN24500CE   (NIFTY, Jun-25 expiry, 24500 strike, Call)
NSE_FO|BANKNIFTY25JUN52000PE
```

Need a resolver function:
```python
def resolve_option_key(underlying: str, expiry: date,
                       strike: int, option_type: str) -> str:
    """
    Build Upstox instrument key for an options contract.
    underlying: "NIFTY" | "BANKNIFTY" | "FINNIFTY"
    option_type: "CE" | "PE"
    """
    exp_str = expiry.strftime("%y%b").upper()   # e.g. "25JUN"
    return f"NSE_FO|{underlying}{exp_str}{strike}{option_type}"
```

**2. Multi-leg order placement**

Add `place_basket_order()` to `UpstoxExecutor`:
```python
async def place_basket_order(self, legs: list[dict], tag: str = "loony") -> list[str]:
    """
    Place multiple option legs simultaneously.
    Returns list of order_ids.
    """
    order_ids = []
    for leg in legs:
        instrument_key = resolve_option_key(
            leg["underlying"], leg["expiry"], leg["strike"], leg["type"]
        )
        order = UpstoxOrder(
            instrument_key=instrument_key,
            quantity=leg["qty"],
            product=UpstoxProduct.NRML,
            order_type=UpstoxOrderType.LIMIT,
            transaction_type=leg["action"],
            price=leg.get("price", 0),
            tag=tag,
        )
        order_id = await self.place_order_raw(order)
        order_ids.append(order_id)
    return order_ids
```

**3. F&O lot sizes**

All F&O orders must be in lot multiples:

| Underlying | Lot Size |
|-----------|----------|
| NIFTY | 75 |
| BANKNIFTY | 30 |
| FINNIFTY | 65 |
| MIDCPNIFTY | 75 |
| SENSEX | 10 |

Add to `risk_manager/risk_manager.py`:
```python
FO_LOT_SIZES = {
    "NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65,
    "MIDCPNIFTY": 75, "SENSEX": 10,
}

def snap_to_lot(symbol: str, quantity: float) -> int:
    lot = FO_LOT_SIZES.get(symbol.upper(), 1)
    return max(lot, int(quantity / lot) * lot)
```

### Files to change
- Create `data_engine/upstox/options_resolver.py` → instrument key builder for F&O
- Edit `execution_engine/upstox_executor.py` → add `place_basket_order()`
- Edit `risk_manager/risk_manager.py` → add `FO_LOT_SIZES` + `snap_to_lot()`
- Edit `strategies/options/*.py` → verify signal metadata format matches new executor

### Acceptance criteria
- [ ] `iron_condor` signal can be placed as a 4-leg basket order in sandbox
- [ ] Lot sizes are respected (no order for 1 NIFTY — must be 75)
- [ ] Options instrument keys resolve to valid Upstox F&O keys

---

## P2-6 · F&O Lot Sizes Ignored for All F&O Orders

**Status:** ❌ Missing  
**Risk:** Any F&O order with quantity not a multiple of the lot size is rejected by Upstox with HTTP 400. The bot treats it as a failed order with no retry.

### Problem

The `RiskManager._position_size()` calculates a float size based on capital × risk.
For equities (lot size = 1) this is fine.
For F&O, the calculated quantity of e.g. `47` would be rejected — it must be `30` (one lot of BANKNIFTY) or `60` (two lots).

This affects:
- Any strategy trading NIFTY / BANKNIFTY futures or options
- The `gamma_scalping`, `theta_decay`, `iron_condor`, `straddle`, `expiry` strategies

### What needs to be built

See P2-5 above for `FO_LOT_SIZES` dict and `snap_to_lot()` function.

Additionally, in `execution_engine/upstox_executor.py`:
```python
def _validate_quantity(self, instrument_key: str, qty: int) -> int:
    """Snap quantity to the nearest valid lot size for F&O instruments."""
    if instrument_key.startswith("NSE_FO") or instrument_key.startswith("BSE_FO"):
        symbol = instrument_key.split("|")[1][:10].rstrip("0123456789CEPJUNFEBMARAPRAUGSEPOCT")
        lot = FO_LOT_SIZES.get(symbol, 1)
        return max(lot, (qty // lot) * lot)
    return qty  # equities: lot size = 1
```

### Files to change
- Edit `risk_manager/risk_manager.py` → add `FO_LOT_SIZES` + `snap_to_lot()`
- Edit `execution_engine/upstox_executor.py` → add `_validate_quantity()` check before every order

### Acceptance criteria
- [ ] NIFTY orders are always multiples of 75
- [ ] BANKNIFTY orders are always multiples of 30
- [ ] Equity orders (lot=1) are unchanged
- [ ] Sandbox test: place BANKNIFTY order with qty=47 → automatically snapped to 30
