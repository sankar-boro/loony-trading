# Options Strategies

`strategies/options/` contains five index-options strategies for Nifty and
BankNifty. They build multi-leg trades from an option chain, the IV surface and
Black-Scholes Greeks.

> **Not wired into trading.** None of these is registered in the
> `MetaStrategyEngine`, and option execution is incomplete: real Upstox F&O
> instrument keys are numeric tokens looked up in the instrument master,
> whereas `data_engine/upstox/options_resolver.py` builds name-based keys such
> as `NSE_FO|NIFTY25JUN24500CE`. Treat this chapter as a description of
> research code. See [Project Status](../appendix/status.md).

Settings live under an `options:` section of the configuration.

## Iron Condor

`iron_condor` · `strategies/options/iron_condor.py`

Sell an OTM call spread and an OTM put spread around the current price:
defined risk, profiting if the index stays inside the short strikes.

| Condition | Default |
|---|---|
| IV rank between | `iv_rank_min` 50 – `iv_rank_max` 85 |
| Trend weak | ADX ≤ `max_adx` 25 |
| Days to expiry | `min_dte` 7 – `max_dte` 30 |
| Short strikes at | `short_delta` 0.20 |
| Wings | `spread_width_pts` 100 points |
| Minimum credit | `min_net_premium` 50 |
| Exit | `profit_target_pct` 50 % of credit; stop at `stop_loss_pct` 100 % |

`adjustment_needed()` flags when price threatens a short strike.

## Theta Decay

`theta_decay` · `strategies/options/theta_decay.py`

Sell OTM options when implied volatility is rich and collect time decay.

| Condition | Default |
|---|---|
| Enter when IV rank ≥ | `iv_rank_entry` 70 (exit idea below `iv_rank_exit` 40) |
| Target delta | `target_delta` 0.25 |
| Days to expiry | 7 – 21 |
| Minimum premium | `min_premium` 30 |
| Exit | 50 % profit (`profit_target_pct`), stop at 2× premium (`stop_loss_mult`) |

## Straddle / Strangle

`straddle_strangle` · `strategies/options/straddle_strangle.py`

Two modes around events:

- **Buy volatility** when IV rank ≤ `buy_iv_rank_max` (30): long ATM straddle
  (or a strangle at `strangle_delta` 0.35 when `use_strangle`) a few days
  before a known event.
- **Sell volatility** when IV rank ≥ `sell_iv_rank_min` (75): after the event,
  to capture the IV crush.

Days to expiry 3–21; target `profit_target_pct` 100 %, stop `stop_loss_pct`
50 %.

## Gamma Scalping

`gamma_scalping` · `strategies/options/gamma_scalping.py`

Buy an ATM straddle (long gamma) and re-hedge delta with the underlying as the
price moves; profitable when realised volatility exceeds implied.

| Condition | Default |
|---|---|
| Realised ÷ implied volatility ≥ | `rv_iv_ratio_min` 1.10 (over `rv_lookback` 20 bars) |
| IV rank ≤ | `max_iv_rank` 60 |
| Near expiry | ≤ `gamma_expiry_dte` 2 days |
| Minimum gamma | `min_gamma` 0.002 |
| Re-hedge when net delta exceeds | `hedge_delta_threshold` 0.10 |

`compute_hedge()` returns the underlying quantity needed to flatten delta.

## Expiry Day (BankNifty 0DTE)

`expiry_day` · `strategies/options/expiry_strategy.py` (`ExpiryDayStrategy`)

Three expiry-day setups: **max-pain pinning** (sell a straddle when spot is
within 0.5 % of max pain, 09:15–13:00), **gamma squeeze follow** (buy options
when spot breaks a key level) and **morning reversal**. It tracks its own open
trades, exits and daily summary.

> It assumes weekly BankNifty expiries. NSE discontinued BankNifty weekly
> contracts in late 2024, so the expiry-day logic needs updating to the
> current expiry calendar before use.

## Shared helpers

- `build_iv_surface()` / `IVSurface` — IV rank, smile, skew, max pain, PCR
  ([Market Intelligence](market-intelligence.md#option-implied-volatility)).
- `feature_engine.greeks` — prices, Greeks, implied volatility, delta-to-strike.
- `options_resolver.nearest_expiry()` / `build_legs_from_signal()` — expiry
  selection and leg construction.
- `UpstoxExecutor.place_basket_order(legs)` — places several legs in sequence,
  snapping each to its lot size (paper fills supported).
- `risk_manager.FO_LOT_SIZES` — fallback lot sizes (NIFTY 65, BANKNIFTY 30,
  FINNIFTY 60, MIDCPNIFTY 120); the instrument master's per-contract lot size
  takes precedence.
