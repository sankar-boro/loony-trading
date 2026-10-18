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
| Sector full | the symbol's sector is at `max_sector_exposure` ([below](#sector-exposure-cap)) |
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
size           = min(size, sector room ÷ price)
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

The executor then rounds the size **down** to whole shares, or whole **lots**
for F&O, using the contract's lot size from the Upstox instrument master,
with `FO_LOT_SIZES` (NIFTY 65, BANKNIFTY 30, FINNIFTY 60, MIDCPNIFTY 120,
SENSEX 10, BANKEX 15) as the fallback. A size below one lot (for example
when the sector cap leaves little room) skips the order rather than rounding
up to a lot nobody sized.

## Sector exposure cap

`risk.max_sector_exposure` (default `0.30`) caps how much capital, at entry
prices, may sit in one sector. Sectors come from `config/instruments.py`;
indices have none and are not capped.

- A new entry is **trimmed** to the sector's remaining room. With ₹5 lakh
  capital and ₹1 lakh already in Banking, a new bank trade may add at most
  ₹50,000.
- When the sector is full, the signal is **rejected**. The live bot logs a
  `block` event: "sector Banking at its 30% exposure cap".
- Set it to `0` to turn the cap off.

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

### Per-strategy loss limits

Built into the live bot: a strategy that loses more than its daily limit,
or several trades in a row, is switched off for the rest of the day. See
[Strategy limits](intraday-controls.md#strategy-limits).

### Portfolio-level checks

The Portfolio Risk dashboard page reports sector concentration, correlation
between holdings and limit breaches ([Portfolio Risk](../dashboard/portfolio-risk.md)).
Sector concentration is also enforced at entry by the
[sector exposure cap](#sector-exposure-cap). The live bot additionally
skips a new entry when its recent returns correlate above
`portfolio.correlation_limit` (0.7) with an open position (needs at least ten
observed prices for both).
