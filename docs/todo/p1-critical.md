# P1 — Critical (Fix Before First Live Trade)

These four gaps would cause real monetary losses or complete bot failure on day one.

---

## P1-1 · Daily Token Auto-Renewal

**Status:** ❌ Missing  
**Risk:** Bot dies every night at 3:30 AM IST. Misses the next full trading day. Open MIS positions cannot be monitored.

### Problem

The Upstox access token expires every day at 3:30 AM IST.
`scripts/upstox_login.py` performs the renewal, but nothing calls it automatically.
The bot runs until the token expires, then all API calls return HTTP 401 and the loop silently fails.

### What needs to be built

**`scripts/auto_login.sh`** — shell wrapper for cron:
```bash
#!/bin/bash
cd /home/sankar/ai_projects/loony-trading
source .venv/bin/activate        # or whatever your venv path is
python scripts/upstox_login.py   # OAuth or --paste-token depending on your setup
# Restart the bot process if it is managed by systemd / supervisor
# systemctl restart loony-trading
```

**Cron entry** (run `crontab -e`):
```
# Renew Upstox token at 8:45 AM IST every weekday (03:15 UTC = 08:45 IST)
15 3 * * 1-5 /home/sankar/ai_projects/loony-trading/scripts/auto_login.sh >> /home/sankar/ai_projects/loony-trading/logs/auto_login.log 2>&1
```

**`main.py` startup check** — add to `UpstoxTradingBot.__init__()`:
```python
from data_engine.upstox.auth import UpstoxAuth
token = self.auth.load_token()
if not token:
    raise RuntimeError(
        "No valid token. Run: python scripts/upstox_login.py"
    )
age_h = (time.time() - self.auth._token_data.get("obtained_at", 0)) / 3600
if age_h > 22:
    raise RuntimeError(
        f"Token is {age_h:.1f}h old — refresh before starting."
    )
```

### Files to change
- Create `scripts/auto_login.sh`
- Edit `main.py` → add token age check in `UpstoxTradingBot.__init__()`
- Edit `scripts/live_signals.py` → abort with clear message if token is stale
- Edit `scripts/paper_trade.py` → same check

### Acceptance criteria
- [ ] Bot restarts automatically every weekday morning with a fresh token
- [ ] Starting with a stale token (>22h old) raises a clear error before any API calls
- [ ] Cron entry is documented in `README.md`

---

## P1-2 · MIS Intraday Auto-Squareoff at 3:15 PM

**Status:** ❌ Missing  
**Risk:** Upstox forcibly closes all MIS positions at 3:20 PM at whatever price the market is. No control over fill price.

### Problem

MIS (Margin Intraday Square-off) orders must be closed before 3:20 PM IST.
The broker closes them automatically at 3:20 PM, but:
- The fill price is at Upstox's discretion (usually market order)
- You get no warning
- The 5-minute window 3:15–3:20 often has very wide spreads

Neither `paper_trade.py` nor `main.py` contain any "close everything at 3:15 PM" logic.

### What needs to be built

**`utils/timeutils.py`** — add helper:
```python
def should_squareoff_mis() -> bool:
    """True from 3:14 PM IST onwards (give 6 minutes before broker does it)."""
    from data_engine.upstox.market_hours import now_ist
    from datetime import time as t
    ist_now = now_ist().time()
    return ist_now >= t(15, 14)
```

**`paper_trade.py`** — add inside the main tick loop:
```python
from utils.timeutils import should_squareoff_mis

if should_squareoff_mis():
    mis_positions = [
        sym for sym, pos in portfolio.positions.items()
        if pos.strategy not in ("CNC", "NRML")   # close MIS-tagged only
    ]
    for sym in mis_positions:
        ltp = prices.get(INSTRUMENTS.get(sym, ""), 0.0)
        msg = portfolio._close_position(sym, ltp, "mis_squareoff_3:15pm")
        print(f"  {yellow('MIS SQUAREOFF')} {msg}")
```

**`main.py` / `UpstoxTradingBot._on_tick()`** — same logic, but calling `executor.place_order()` to close the real position via Upstox API.

**`execution_engine/upstox_executor.py`** — add:
```python
async def squareoff_all_mis(self) -> list[str]:
    """Close all open MIS positions. Call at 3:14 PM IST."""
    positions = await self.get_positions()
    closed = []
    for pos in positions:
        if pos.get("product") == "MIS" and int(pos.get("quantity", 0)) != 0:
            await self.place_order(...)   # SELL/BUY to close
            closed.append(pos["trading_symbol"])
    return closed
```

### Files to change
- Edit `utils/timeutils.py` → add `should_squareoff_mis()`
- Edit `scripts/paper_trade.py` → add squareoff check in tick loop
- Edit `main.py` → add squareoff in `_on_tick` handler
- Edit `execution_engine/upstox_executor.py` → add `squareoff_all_mis()`

### Acceptance criteria
- [ ] All MIS positions are closed by 3:15 PM IST with a logged message
- [ ] CNC and NRML positions are NOT closed (only MIS)
- [ ] Squareoff fires exactly once per session (not on every tick after 3:15)
- [ ] Paper trade session shows the squareoff in the activity log

---

## P1-3 · Position State Persistence on Crash

**Status:** ❌ Missing  
**Risk:** If the bot crashes (network drop, OOM, Ctrl+C), all in-memory positions are forgotten. On restart, the bot re-enters trades already open in the market, doubling exposure with no stop-loss on the orphan position.

### Problem

All position tracking is in-memory only:
- `PaperPortfolio.positions` (dict, `paper_trade.py`)
- `RiskManager._positions` (dict, `risk_manager.py`)
- `PortfolioManager` (in-memory, `portfolio_manager/portfolio.py`)

Nothing is written to disk. A crash = total amnesia.

### What needs to be built

**`data/live_positions.json`** — written on every tick:
```json
{
  "snapshot_ts": "2025-05-27T10:32:15+05:30",
  "mode": "paper",
  "capital": 500000,
  "cash": 423150.0,
  "positions": {
    "RELIANCE": {
      "direction": 1,
      "size": 10,
      "entry_price": 2847.5,
      "stop_loss": 2790.0,
      "take_profit": 2960.0,
      "trailing_stop_pct": 0.02,
      "strategy": "ema_crossover",
      "entry_time": "10:22:14"
    }
  },
  "closed_today": 3,
  "realised_pnl": 1240.0
}
```

**`paper_trade.py`** — save snapshot every tick:
```python
def _save_state(portfolio: PaperPortfolio, path: Path):
    state = {
        "snapshot_ts": datetime.now().isoformat(),
        "mode": "paper",
        "capital": portfolio.initial_capital,
        "cash": portfolio.cash,
        "positions": {
            sym: {
                "direction": p.direction,
                "size": p.size,
                "entry_price": p.entry_price,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "trailing_stop_pct": p.trailing_stop_pct,
                "strategy": p.strategy,
                "entry_time": p.entry_time,
            }
            for sym, p in portfolio.positions.items()
        },
        "realised_pnl": portfolio.realised_pnl,
        "closed_today": len(portfolio.closed_trades),
    }
    path.write_text(json.dumps(state, indent=2))
```

**On startup** — load existing state instead of starting fresh:
```python
state_file = ROOT / "data" / "live_positions.json"
if state_file.exists():
    state = json.loads(state_file.read_text())
    age = (datetime.now() - datetime.fromisoformat(state["snapshot_ts"])).total_seconds()
    if age < 3600:   # only restore if snapshot is < 1 hour old
        # restore positions into portfolio
        print(f"Restored {len(state['positions'])} positions from last session")
```

### Files to change
- Edit `scripts/paper_trade.py` → add `_save_state()`, call every tick + on clean exit
- Edit `risk_manager/risk_manager.py` → add `save_state()` / `load_state()` methods
- Edit `main.py` → call `risk_manager.save_state()` every N ticks

### Acceptance criteria
- [ ] `data/live_positions.json` exists and updates every tick
- [ ] On restart, the existing state is loaded and positions are restored
- [ ] If snapshot is >1 hour old, it is ignored (stale state is worse than no state)
- [ ] Clean shutdown (`KeyboardInterrupt`) deletes the state file

---

## P1-4 · Market Hours Enforcement in Integration Scripts

**Status:** ❌ Missing  
**Risk:** `live_signals.py` and `paper_trade.py` run 24/7, including weekends and NSE holidays. They make API calls that fail silently, generate garbage signals on zero-volume data, and waste API rate limit quota.

### Problem

`data_engine/upstox/market_hours.py` has a correct `is_market_open()` function and a complete 2025 NSE holiday calendar. It is never called from `live_signals.py`, `paper_trade.py`, or `market_watch.py`.

### What needs to be built

**`live_signals.py`** — add at the top of `_run_scan()`:
```python
from data_engine.upstox.market_hours import (
    is_market_open, next_market_open, minutes_to_close
)

if not is_market_open():
    next_open = next_market_open()
    print(f"\n{dim('Market is closed.')}  Next open: {next_open.strftime('%a %d-%b %H:%M IST')}")
    return

mins_left = minutes_to_close()
if mins_left < 10:
    print(f"\n{yellow(f'Market closes in {mins_left} min — last scan.')}") 
```

**`paper_trade.py`** — add at the start of the main `while True:` loop:
```python
from data_engine.upstox.market_hours import is_market_open, next_market_open

if not is_market_open():
    next_open = next_market_open()
    wait_sec = (next_open - datetime.now(IST)).total_seconds()
    print(f"\n  Market is closed. Resuming at {next_open.strftime('%H:%M IST')} "
          f"({wait_sec/3600:.1f}h from now)")
    time.sleep(min(wait_sec, 3600))   # sleep max 1h, re-check
    continue
```

**`scripts/market_watch.py`** — same guard (already has some partial handling).

### Files to change
- Edit `scripts/live_signals.py` → add market hours guard + minutes-to-close warning
- Edit `scripts/paper_trade.py` → add market hours guard with smart sleep
- Edit `scripts/market_watch.py` → add pre-open and post-close messages

### Acceptance criteria
- [ ] Running `live_signals.py` on a Saturday prints "Market is closed" and exits
- [ ] Running `paper_trade.py` on a holiday sleeps until next open, then resumes
- [ ] A "market closes in 10 min" warning appears in the last scan before 3:30 PM
- [ ] No API calls are made outside market hours
