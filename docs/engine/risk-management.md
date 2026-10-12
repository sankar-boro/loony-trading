# Risk Management

`risk_manager/risk_manager.py` decides whether a signal may be traded, how big
the position is, and when an open position must be closed. Every order the
live bot places goes through it.

## Settings

```yaml
risk:
  max_risk_per_trade: 0.01        # risk 1 % of capital per trade
  max_daily_drawdown: 0.05        # stop opening trades after −5 % in a day
  max_concurrent_trades: 10
  max_portfolio_risk: 0.20        # one position may use at most 20 % of capital
  stop_loss_atr_multiplier: 2.0
  take_profit_atr_multiplier: 3.0
  trailing_stop_pct: 0.02
  use_kelly_criterion: false
  kelly_fraction: 0.25
```

(`stop_loss_atr_multiplier` and `take_profit_atr_multiplier` document intent;
stops actually come from each strategy's signal.)

## Validating a signal

`validate_signal(signal)` rejects a signal when:

| Rule | Check |
|---|---|
| Too many positions | open positions ≥ `max_concurrent_trades` |
| Bad day | today's realised P&L < −`max_daily_drawdown` × capital |
| Weak signal | confidence < 0.5 |
| Already positioned | any position is open in that symbol |

The last rule means **one position per symbol**: no pyramiding, and no opening
the other way on top of a position. The live bot handles opposite signals
itself — it closes the open position and stays flat (see
[Architecture of the Bot](architecture.md#the-tick-loop)).

Daily P&L and the trade count reset when a new IST trading day begins, so the
drawdown limit really is per day.

## Position sizing

`size_position(signal)`:

```
risk amount    = capital × max_risk_per_trade
risk per share = |entry price − stop-loss|
size           = risk amount ÷ risk per share
size           = min(size, capital × max_portfolio_risk ÷ price)
```

Example: ₹5,00,000 capital, 1 % risk = ₹5,000; entry ₹2,800, stop ₹2,750 →
₹50 risk per share → 100 shares (₹2,80,000)… capped by the 20 % limit at
₹1,00,000 ÷ ₹2,800 = 35 shares. The tighter the stop, the bigger the position
— until the exposure cap binds.

With `use_kelly_criterion: true`, size follows the fractional Kelly formula
instead: win probability = signal confidence, payoff = reward ÷ risk,
`kelly = p − (1 − p) ÷ payoff`, scaled by `kelly_fraction` (default ¼ Kelly)
and floored at zero. Only use it once you trust that strategy confidences are
calibrated probabilities.

If the stop equals the entry price, a tiny fallback size is used and a warning
logged.

The executor then rounds the size to whole shares — or whole **lots** for F&O
(at least one lot) using the contract's lot size from the Upstox instrument
master, with `FO_LOT_SIZES` (NIFTY 65, BANKNIFTY 30, FINNIFTY 60,
MIDCPNIFTY 120, SENSEX 10, BANKEX 15) as the fallback.

## Managing open positions

A `Position` holds symbol, direction, entry price, size, stop-loss,
take-profit, trailing percentage, strategy, peak price, current P&L and entry
time.

`update_all({symbol: price})` runs on every tick for that symbol:

1. **Trailing stop** — for a long, when price makes a new peak the stop rises to
   `peak × (1 − trailing_stop_pct)` (never lowered); for a short, the mirror
   image. With the default 2 %, a long that rallies 10 % has locked in about 8 %.
2. **Stop hit** — price at or through the stop → close, reason `stop_loss`.
3. **Target hit** — price at or through the take-profit → close, reason
   `take_profit`.

`close_position(pos, price, reason)` books P&L into capital and daily P&L and
removes the position.

## Other risk components

These are complete libraries that the bot does **not** call yet; they are
available for scripts and future wiring.

### CVaR limits

`risk_manager/cvar.py` computes Value-at-Risk and Conditional VaR (expected
shortfall — the average loss in the worst 5 % of outcomes) three ways:
historical, parametric (normal) and Cornish-Fisher (adjusted for skew and fat
tails). `CVaRRiskManager` records realised P&L per strategy and:

- shrinks all new positions when portfolio CVaR95 exceeds 3 % of capital
  (`portfolio_size_multiplier()`, floor 0.2×);
- flags a strategy whose CVaR95 exceeds 1.5 % of capital
  (`is_strategy_disabled()`);
- needs at least 20 observations before acting.

### Circuit breakers

`CircuitBreakerDetector` — see [Market Hours and Calendar](market-calendar.md#circuit-breakers).

### Live P&L tracker

`analytics/live_pnl.py` (`LivePnLTracker`) applies per-strategy kill switches:
a strategy losing more than 2 % of capital in a day is disabled for the day,
portfolio drawdown beyond 5 % halts everything, and five consecutive losses
halve that strategy's size. See [Portfolio and Analytics](portfolio-analytics.md).

### Portfolio-level checks

The Portfolio Risk dashboard page reports sector concentration, correlation
between holdings and limit breaches, but only as warnings
([Portfolio Risk](../dashboard/portfolio-risk.md)). The live bot additionally
skips a new entry when its recent returns correlate above
`portfolio.correlation_limit` (0.7) with an open position (needs at least ten
observed prices for both).
