# Trading Bot — Gap Analysis & TODO

Complete audit of what is missing before this bot can trade real money reliably.
Items are organised by priority tier, then into individual task files.

**Audit date:** 2026-05-27  
**Codebase commit:** `5231276`

---

## Priority Tiers

| Tier | Label | Meaning |
|------|-------|---------|
| 🔴 P1 | **Critical** | Would lose real money today if ignored |
| 🟠 P2 | **Important** | Trading incorrectly (silent P&L errors) |
| 🟡 P3 | **Operational** | Flying blind — no visibility into what the bot is doing |
| 🔵 P4 | **Infrastructure** | Reliability & maintainability gaps |

---

## File Index

| File | Tier | Topics |
|------|------|--------|
| [p1-critical.md](p1-critical.md) | 🔴 P1 | Daily token renewal, MIS squareoff, crash recovery, market hours |
| [p2-trading-correctness.md](p2-trading-correctness.md) | 🟠 P2 | Corporate actions, transaction costs, ML training, intraday data, options execution, F&O lots |
| [p3-observability.md](p3-observability.md) | 🟡 P3 | Telegram alerts, daily P&L report, trade journal, benchmark comparison |
| [p4-infrastructure.md](p4-infrastructure.md) | 🔵 P4 | NSE holidays 2026+, Protobuf SDK, dashboard, strategy weight tuning |

---

## Quick Status

```
Total gaps identified:   18
P1 Critical:              4   (fix these before first live trade)
P2 Important:             6   (fix before trusting backtest results)
P3 Operational:           4   (fix before leaving unattended)
P4 Infrastructure:        4   (fix within first month)
```

---

## Fastest Path to "Properly Live"

Fix in this order — estimated 1–2 days of work total:

1. **[P1-1]** Add daily token renewal cron → `scripts/auto_login.sh`
2. **[P1-2]** Add MIS squareoff at 3:15 PM in `paper_trade.py` + `main.py`
3. **[P1-3]** Write position state to `data/live_positions.json` on every tick
4. **[P1-4]** Add `is_market_open()` guard to `live_signals.py` + `paper_trade.py`
5. **[P2-3]** Run `python main.py --mode train` to produce ML model files
6. **[P2-6]** Fix F&O lot sizes in `risk_manager.py`
7. **[P3-1]** Wire `TelegramAlerter` into `paper_trade.py` and `main.py`
8. **[P2-2]** Fix transaction cost constants in `execution_engine/upstox_executor.py`

After these 8 items the bot: auto-starts daily, handles intraday margin correctly,
survives crashes without doubling positions, only runs during market hours,
and notifies you on every trade and risk event.
