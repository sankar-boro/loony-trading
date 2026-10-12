# Execution

`execution_engine/upstox_executor.py` (`UpstoxExecutor`) turns approved signals
into orders — real ones through the Upstox REST API in live mode, simulated
fills with realistic Indian costs in paper mode.

```python
executor = UpstoxExecutor(auth, registry, risk_manager, cfg, mode="paper")   # or "live"
order = await executor.execute_signal(signal)
```

## Products and order types

| Product | Meaning | Closed by |
|---|---|---|
| `CNC` | Cash and carry — delivery equity, no leverage | You (held across days) |
| `MIS` | Margin intraday square-off | The bot at 15:14, Upstox at 15:20 |
| `NRML` | Normal — F&O carried overnight | You / expiry |

The product for every order comes from `exchanges.upstox.default_product`
(`CNC` by default); `execution.upstox_product`, if set, overrides it.

| Order type | Needs | Chosen when `execution.order_type` is |
|---|---|---|
| `MARKET` | — | `market`; or `smart` with confidence > 0.85 |
| `LIMIT` | price | `limit` (default); or `smart` with confidence ≤ 0.85 |
| `SL`, `SL-M` | trigger (and price) | available via the API; not chosen automatically |

Limit prices are rounded to the instrument's tick size.

## execute_signal, step by step

1. `RiskManager.validate_signal()` — stop if rejected (see
   [Risk Management](risk-management.md#validating-a-signal)).
2. Resolve the instrument key; read lot and tick size from the registry.
3. Size: `RiskManager.size_position()`, rounded to whole lots (≥ 1 lot), then
   snapped again to the contract's lot size for F&O.
4. Build the order: BUY/SELL from the signal, the default product, the chosen
   order type, tag `loony-<strategy>`.
5. **Paper**: simulated fill (below). **Live**: place it once, then poll its
   status every second for up to 30 s.
6. **Live, still not filled after the poll** (typically an unfilled limit
   order): the order is **cancelled**. If part of it filled, the bot tracks only
   the filled quantity; otherwise it records nothing. Nothing is left working
   at the broker.
7. On a fill: open a `Position` in the risk manager at the actual fill price,
   record the order, and call the `on_fill` callbacks (the bot logs to
   `logs/trades.jsonl`).

**Order placement is never retried.** Placing an order is not idempotent: a
request that times out may still have reached the exchange, and a retry would
create a duplicate. A failed placement is logged ("check the Upstox order
book") and treated as rejected; if it did go through, the position appears at
the broker and [reconciliation](position-safety.md#broker-reconciliation) alerts
on it.

All HTTP calls from async code run in a worker thread (`_post_async`,
`_get_async`, …), so a slow order request never stalls the WebSocket loop or
the stop checks of other positions.

## Paper fills and costs

A paper fill happens immediately at the signal price adjusted by
`execution.slippage_pct` (default 0.05 %) against you — higher for buys, lower
for sells — and the charges below are computed and logged.

`_compute_charges(price, qty, side, product)` models NSE equity charges:

| Charge | Intraday (MIS, NRML) | Delivery (CNC) |
|---|---|---|
| Brokerage | lower of ₹20 and 0.03 % | ₹0 |
| STT | 0.025 % on the sell side | 0.1 % on both sides |
| Exchange transaction charge | 0.00345 % | 0.00345 % |
| GST | 18 % of brokerage + exchange charge | same |
| SEBI fee | 0.0001 % (₹10 per crore) | same |
| Stamp duty | 0.003 % on the buy side | 0.015 % on the buy side |
| **Typical round trip** | **≈ 0.055 %** | **≈ 0.21 %** |

These figures are for equities; F&O charges differ (STT on premium for
options, different exchange rates). Rates change with budgets and exchange
circulars — check them periodically. The backtester uses the round-trip
figures `execution.commission_intraday` (0.00055) and
`execution.commission_delivery` (0.0021) directly.

## Closing positions

`close_position(pos, price, reason)` sends a MARKET order in the opposite
direction for the position's size (rounded to lots), in the default product,
then books the P&L in the risk manager. In paper mode it fills at the given
price with slippage.

## Other operations

| Method | Purpose |
|---|---|
| `modify_order(order_id, quantity, price, order_type, trigger_price)` | Change a working order |
| `cancel_order(order_id)`, `cancel_all_orders()` | Cancel one / every open order |
| `place_gtt(symbol, side, qty, product, trigger, limit, trigger_type)` | Good-till-triggered order (`single` or `two-leg`) — persists at Upstox until triggered or cancelled |
| `squareoff_all_mis()` | Close every open MIS position at the broker with market orders (live); no-op in paper |
| `place_basket_order(legs)` | Several option legs in sequence, each lot-snapped |
| `execute_options_signal(signal)` | Build legs from an options signal and place them as a basket |
| `fetch_broker_quantities()` | Net quantity per instrument from positions + holdings — raises on any API error |
| `get_positions()`, `get_holdings()`, `get_funds()`, `get_order_book()` | Account queries (return empty on error) |

After-market orders are supported through `UpstoxOrder.is_amo`.

## Smart order algorithms

`execution_engine/smart_order.py` provides algorithms for splitting a large
order over time. They produce schedules and track execution, but the bot does
not use them yet.

| Class | Behaviour |
|---|---|
| `TWAPOrder` | Equal slices at fixed intervals |
| `VWAPOrder` | Slices weighted by the typical NSE intraday volume curve (heavier at the open and the last hour); `apply_participation_limit()` caps each slice at a share of actual market volume |
| `TransactionCostAnalyzer` | Post-trade analysis: slippage vs arrival price, market impact vs pre-trade VWAP, charges in basis points |

## Crypto executor

`execution_engine/executor.py` is the older generic executor for ccxt
exchanges (Binance), used only by the dormant crypto add-on. It still retries
order placement `execution.retry_attempts` times.
