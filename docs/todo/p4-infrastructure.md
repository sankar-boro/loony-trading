# P4 — Infrastructure (Reliability & Maintainability)

These gaps won't cause immediate losses but will cause operational problems over weeks to months.

---

## P4-1 · NSE Holiday Calendar Ends in 2025

**Status:** ⚠️ Will break in 2026  
**Risk:** From January 1, 2026 onwards, every NSE holiday is treated as a trading day. The bot will attempt API calls, generate signals, and potentially place orders on closed exchange days.

### Problem

`data_engine/upstox/market_hours.py` contains:
```python
_NSE_HOLIDAYS_2025: List[date] = [
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    ...
    date(2025, 12, 25),  # Christmas
]
```

The list is hardcoded and ends in 2025. There is no mechanism to fetch or update it for 2026 and beyond.

Also note: `date(2025, 10, 2)` appears **twice** — Mahatma Gandhi Jayanti and Dussehra are both on Oct 2 in the list, but Dussehra 2025 is actually October 2 (it overlaps). This should be verified against the official NSE calendar.

### What needs to be built

**Option A (Recommended): Fetch from NSE API on startup**

NSE publishes the official holiday calendar at:
```
GET https://www.nseindia.com/api/holiday-master?type=trading
```

```python
# data_engine/upstox/market_hours.py

import json
import time
from pathlib import Path

_HOLIDAY_CACHE = Path("data/nse_holidays.json")
_HOLIDAY_CACHE_TTL = 86400 * 30   # refresh monthly

def _fetch_nse_holidays(year: int) -> list[date]:
    """Fetch NSE trading holidays from NSE website with caching."""
    if _HOLIDAY_CACHE.exists():
        cached = json.loads(_HOLIDAY_CACHE.read_text())
        if time.time() - cached.get("fetched_at", 0) < _HOLIDAY_CACHE_TTL:
            return [date.fromisoformat(d) for d in cached.get("holidays", [])]
    
    try:
        import requests
        r = requests.get(
            "https://www.nseindia.com/api/holiday-master?type=trading",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        data = r.json()
        holidays = []
        for entry in data.get("CM", []):   # CM = Capital Markets segment
            try:
                holidays.append(date.fromisoformat(entry["tradingDate"][:10]))
            except Exception:
                pass
        _HOLIDAY_CACHE.write_text(json.dumps({
            "fetched_at": time.time(),
            "holidays": [d.isoformat() for d in holidays],
        }))
        return holidays
    except Exception:
        return []   # fall back to hardcoded list

def _get_holidays(year: int) -> list[date]:
    live = _fetch_nse_holidays(year)
    if live:
        return [d for d in live if d.year == year]
    # Fallback to hardcoded 2025 list
    return _NSE_HOLIDAYS_2025
```

**Option B: Extend the hardcoded list annually**

Add `_NSE_HOLIDAYS_2026` manually each December based on NSE's official circular.
Less code, but requires manual maintenance every year.

### Files to change
- Edit `data_engine/upstox/market_hours.py` → add dynamic holiday fetching
- Create `data/nse_holidays.json` in `.gitignore` (it's runtime data)
- Fix the duplicate `date(2025, 10, 2)` entry in the existing list

### Acceptance criteria
- [ ] `is_market_open()` correctly identifies NSE holidays in 2026
- [ ] Holiday list is cached to `data/nse_holidays.json` and refreshed monthly
- [ ] Falls back to hardcoded 2025 list if the NSE API is unreachable
- [ ] Duplicate date in 2025 list is fixed

---

## P4-2 · Protobuf SDK Not Verified on Startup

**Status:** ⚠️ Silent risk  
**Risk:** The WebSocket feed (`UpstoxFeed`) says it uses the Upstox Python SDK protobuf decoder "when available", falling back to raw struct parsing. If the SDK is not installed, the fallback may silently decode tick data incorrectly — giving corrupt prices to all strategies.

### Problem

From `data_engine/upstox/upstox_feed.py`:
```
# Uses upstox-python-sdk decoder when available,
# falls back to raw struct parsing
```

There is no check on startup that verifies:
1. Is `upstox-python-sdk` installed?
2. If using fallback: has the fallback been tested against known price data?
3. If feed data is corrupted: is there any sanity check (e.g., price is 0, price is 10× yesterday's close)?

### What needs to be built

**`data_engine/upstox/upstox_feed.py`** — add startup check:
```python
def _check_protobuf_decoder() -> str:
    """Return 'sdk' if upstox-python-sdk is available, 'fallback' otherwise."""
    try:
        from upstox_client import MarketDataFeedV3
        return "sdk"
    except ImportError:
        import warnings
        warnings.warn(
            "upstox-python-sdk not installed. Using fallback protobuf decoder.\n"
            "Install for reliable feed: pip install upstox-python-sdk",
            RuntimeWarning,
            stacklevel=2,
        )
        return "fallback"

# Call in __init__:
self._decoder_mode = _check_protobuf_decoder()
logger.info(f"WebSocket protobuf decoder: {self._decoder_mode}")
```

**Price sanity check in tick handler:**
```python
def _validate_tick(self, event: MarketEvent, prev_price: float) -> bool:
    """Return False if the tick looks corrupt."""
    if event.ltp <= 0:
        return False
    if prev_price > 0:
        change_pct = abs(event.ltp - prev_price) / prev_price
        if change_pct > 0.20:   # >20% move in one tick = suspicious
            logger.warning(
                f"Suspicious tick: {event.symbol} "
                f"prev={prev_price:.2f} now={event.ltp:.2f} "
                f"change={change_pct:.1%}"
            )
            return False
    return True
```

**`scripts/test_upstox.py`** — the WebSocket test already exists (`[10] WebSocket`), but add a price validation step:
```python
# After receiving first tick:
r.check("WebSocket LTP is a sane number",
        0 < received_ltp < 1_000_000,
        detail=f"LTP: {received_ltp}")
```

**Install instruction** to add to `README.md` / `quickstart.md`:
```bash
pip install upstox-python-sdk   # required for reliable WebSocket feed
```

### Files to change
- Edit `data_engine/upstox/upstox_feed.py` → add `_check_protobuf_decoder()` + `_validate_tick()`
- Edit `scripts/test_upstox.py` → enhance WebSocket test with price sanity check
- Edit `docs/quickstart.md` → add `upstox-python-sdk` to install instructions

### Acceptance criteria
- [ ] Starting the bot prints `WebSocket protobuf decoder: sdk` (or `fallback` with a warning)
- [ ] A corrupt tick (LTP=0 or 20%+ move) is logged as a warning and dropped
- [ ] `test_upstox.py [10]` validates the decoded LTP value is in a sane range
- [ ] `pip install upstox-python-sdk` is documented in quickstart

---

## P4-3 · Streamlit Dashboard Is a Stub

**Status:** ⚠️ Partially implemented  
**Risk:** `dashboard/app.py` can be started (`streamlit run dashboard/app.py`) but the live positions, equity curve, and strategy performance sections depend on data files that don't exist or aren't written by the bot.

### Problem

The dashboard reads from:
- `data/live_positions.json` → not written (see P1-3)
- `logs/trades.jsonl` → written by `trade_logger.py` in live mode only
- Live prices via Upstox API → requires a valid token
- Config via `config/settings` → works

Sections that need fixing:

| Section | Status | Blocker |
|---------|--------|---------|
| Market status widget | ✅ Works | None |
| Token status | ✅ Works | None |
| Live positions | ❌ Empty | P1-3 (no state file) |
| Open P&L | ❌ 0 | P1-3 (no state file) |
| Equity curve | ❌ Empty | No equity curve file written |
| Trade history | ⚠️ Works in live mode | Needs `logs/trades.jsonl` |
| Strategy signals | ❌ Not wired | No data bridge from bot to dashboard |

### What needs to be built

**1. Equity curve file** — bot writes `data/equity_curve.jsonl` on every tick:
```python
# In paper_trade.py / main.py tick loop:
equity_file = ROOT / "data" / "equity_curve.jsonl"
with open(equity_file, "a") as f:
    f.write(json.dumps({
        "ts": datetime.now().isoformat(),
        "total_value": portfolio.total_value,
        "cash": portfolio.cash,
        "unrealised": portfolio.unrealised_pnl,
        "realised": portfolio.realised_pnl,
    }) + "\n")
```

**2. Dashboard reads state files** — `dashboard/app.py` should read `data/live_positions.json`:
```python
state_file = ROOT / "data" / "live_positions.json"
if state_file.exists():
    state = json.loads(state_file.read_text())
    positions_df = pd.DataFrame(state.get("positions", {}).values())
```

**3. Auto-refresh** — dashboard should update every 30 seconds:
```python
# Already in app.py header — verify it's implemented:
st.markdown("""<meta http-equiv="refresh" content="30">""", unsafe_allow_html=True)
# OR use streamlit's built-in:
import time
while True:
    # render dashboard
    time.sleep(30)
    st.rerun()
```

**4. Equity curve chart** — add Plotly chart reading `data/equity_curve.jsonl`:
```python
if Path("data/equity_curve.jsonl").exists():
    eq_df = pd.read_json("data/equity_curve.jsonl", lines=True)
    fig = go.Figure(go.Scatter(
        x=eq_df["ts"], y=eq_df["total_value"],
        mode="lines", name="Portfolio Value"
    ))
    st.plotly_chart(fig, use_container_width=True)
```

### Files to change
- Fix P1-3 first (positions state file) — dashboard depends on it
- Edit `scripts/paper_trade.py` → write `data/equity_curve.jsonl`
- Edit `main.py` → same equity curve write
- Edit `dashboard/app.py` → read `live_positions.json` + `equity_curve.jsonl`

### Acceptance criteria
- [ ] `streamlit run dashboard/app.py` shows open positions when bot is running
- [ ] Equity curve chart is visible and updates on each page refresh
- [ ] Dashboard works for both paper and live modes
- [ ] Dashboard shows "Bot not running" gracefully when no state file exists

---

## P4-4 · Strategy Weights Are All 1.0 (Untuned)

**Status:** ⚠️ Suboptimal  
**Risk:** All 17 strategies vote with equal weight in `MetaStrategyEngine`. A strategy with 40% win rate votes as loudly as one with 70% win rate. This dilutes the signal quality of the best strategies.

### Problem

In `config/settings.yaml`:
```yaml
strategies:
  enabled: []       # all enabled
  weights: {}       # all weight = 1.0
```

In `MetaStrategyEngine.best_signal()`, confidence × weight determines the winner.
With all weights = 1.0, only raw confidence score matters, which is computed internally by each strategy.

Some strategies (like `MLClassifierStrategy`) output calibrated 0–1 confidence values.
Others (like `EmaCorossoverStrategy`) might always output 0.7. Without weight tuning,
the ensemble is unbalanced.

### What needs to be built

**Step 1: Run individual strategy backtests**

```bash
# Backtest each strategy individually on 1 year of RELIANCE data
python scripts/backtest_runner.py \
    --symbols RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK \
    --strategies ema_crossover \
    --days 365

# Repeat for each strategy, record Sharpe ratio
```

**Step 2: Compute weights from Sharpe ratios**

```python
# Strategy Sharpe ratios from individual backtests (example values):
sharpe_by_strategy = {
    "ema_crossover":          1.42,
    "rsi_reversion":          1.18,
    "bollinger_reversion":    0.84,
    "zscore_reversion":       0.91,
    "vwap_reversion":         1.05,
    "macd_momentum":          1.33,
    "rsi_momentum":           0.98,
    "volume_momentum":        1.21,
    "support_resistance":     1.15,
    "atr_breakout":           0.77,
    "supertrend":             1.38,
    "donchian_breakout":      1.09,
    "candlestick_patterns":   0.71,
    "order_book_imbalance":   1.44,
    "ml_classifier":          1.67,
}

# Normalize: weight = max(0, sharpe) / sum(max(0, sharpe))
import numpy as np
sharpes = np.array(list(sharpe_by_strategy.values()))
weights = np.maximum(sharpes, 0) / np.sum(np.maximum(sharpes, 0))
weights_dict = dict(zip(sharpe_by_strategy.keys(), weights.round(3).tolist()))
```

**Step 3: Update `config/settings.yaml`**

```yaml
strategies:
  weights:
    ema_crossover:       0.082
    rsi_reversion:       0.068
    bollinger_reversion: 0.048
    macd_momentum:       0.077
    ml_classifier:       0.096
    order_book_imbalance: 0.083
    # ... etc
```

**`scripts/tune_weights.py`** — automate this process:
```
python scripts/tune_weights.py --days 180
```
Runs each strategy individually, records Sharpe, computes normalized weights, writes to `config/settings.yaml`.

### Files to change
- Create `scripts/tune_weights.py` → automates individual strategy backtest + weight computation
- Edit `config/settings.yaml` → update weights after running `tune_weights.py`
- Edit `MetaStrategyEngine.best_signal()` → verify it uses `signal.weight` or strategy weight from config correctly

### Acceptance criteria
- [ ] `tune_weights.py` runs and updates `settings.yaml` with computed weights
- [ ] `MetaStrategyEngine` respects non-uniform weights in signal selection
- [ ] Strategies with Sharpe < 0 get weight = 0 (effectively disabled)
- [ ] Re-running `tune_weights.py` after more data updates weights without manual editing
