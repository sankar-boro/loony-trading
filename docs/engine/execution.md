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

### Shorts need MIS

A SELL signal on a flat symbol would open a short. NSE does not allow an
overnight short in the cash segment: Upstox rejects it, or a short that slips
through ends in an exchange auction with a penalty. So new shorts are opened
only on `MIS` (closed by the intraday squareoff) or `NRML` (F&O);
`risk_manager.can_open_short()` holds the rule. On `CNC`:

- a SELL that closes an open long works as usual;
- a SELL on a flat symbol is refused. `execute_signal` returns nothing and
  logs a warning. The bot logs a `block` event ("no short entries on CNC") on
  the [Intraday Desk](../dashboard/intraday-desk.md). The backtester skips
  the entry the same way.

Paper mode goes through the same executor, so paper results no longer
include shorts the live bot could not make.

| Order type | Needs | Chosen when `execution.order_type` is |
|---|---|---|
| `MARKET` | — | `market`; or `smart` with confidence > 0.85 |
| `LIMIT` | price | `limit` (default); or `smart` with confidence ≤ 0.85 |
| `SL`, `SL-M` | trigger (and price) | available via the API; not chosen automatically |

Limit prices are rounded to the instrument's tick size.

## execute_signal, step by step

1. `RiskManager.validate_signal()` — stop if rejected (see
   [Risk Management](risk-management.md#validating-a-signal)).
   A short entry on a product that cannot hold one (CNC) is also refused
   ([Shorts need MIS](#shorts-need-mis)).
2. Resolve the instrument key; read lot and tick size from the registry.
3. Size: `RiskManager.size_position()`, rounded to whole lots (≥ 1 lot), then
   snapped again to the contract's lot size for F&O.
4. Build the order: BUY/SELL from the signal, the default product, the chosen
   order type, tag `loony-<strategy>`.
5. **Paper**: simulated fill (below). **Live**: place it once, then poll its
   status every second for up to 30 s.
6. **Live, a limit order still not filled after the poll** is **chased**
   ([below](#limit-order-chasing)).
7. **Live, still not filled after chasing**: the order is **cancelled**. If
   part of it filled, the bot tracks only the filled quantity; otherwise it
   records nothing. Nothing is left working at the broker.
8. Every order, filled or not, is written to the
   [execution log](#execution-quality).
9. On a fill: open a `Position` in the risk manager at the actual fill price,
   record the order, and call the `on_fill` callbacks (the bot logs to
   `logs/trades.jsonl`).

### Limit-order chasing

A live limit order still working after the 30-second poll is re-priced
toward the market up to `execution.chase_attempts` (2) times. Each attempt
moves the limit to the last traded price, at least one tick, but never more
than `max_chase_pct` (0.3 %) from the original limit. It then waits
`chase_wait_sec` (10 s) for a fill. When the cap is reached, or the attempts
run out, the rest is cancelled as before. Market orders are never chased.
Set `chase_attempts: 0` to turn chasing off.

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

**Live, a close is booked only if it filled.** A rejected or failed market
order returns nothing and the position stays tracked. The next stop check
retries, but no sooner than 30 seconds after the failure, so a broker that
keeps rejecting is not flooded with orders. Before 2026-10-19 a failed close
was booked at ₹0: a fake P&L, and a position the bot no longer tracked while
it was still open at the broker.

## Execution quality

Every entry and exit order, paper and live, adds one line to
`logs/executions.jsonl`:

```json
{"ts": "2026-10-19T09:41:12+05:30", "mode": "live", "kind": "entry", "symbol": "TCS",
 "strategy": "donchian_breakout", "side": "BUY", "order_type": "LIMIT", "product": "MIS",
 "qty": 40, "filled_qty": 40, "decision_price": 4012.5, "limit_price": 4012.5,
 "fill_price": 4014.0, "slippage_bps": 3.74, "outcome": "filled", "chases": 1, "latency_ms": 31840}
```

Slippage is measured against the **decision price**: the price the signal,
or the stop or target check, saw when it decided to trade. It is in basis
points, and positive means a cost. `outcome` is `filled`, `partial`,
`unfilled` (cancelled by the bot) or `rejected`.

`analytics/execution_quality.report()`, `python scripts/execution_report.py`
and the **Execution quality** tab on the Trades page summarise the log:
- fill rate;
- average, median and 90th-percentile slippage;
- slippage cost in rupees;
- broken down by entry/exit, order type, strategy, hour of day, and the
  number of chases for limit orders.

## GTT orders

`place_gtt`, `modify_gtt`, `cancel_gtt`, `get_gtt` and `get_gtt_orders`
use Upstox's **v3** GTT API (`/v3/order/gtt/...`). A single-leg GTT has one
`ENTRY` rule: trigger `ABOVE` or `BELOW` a price, product `D` (delivery) or
`I` (intraday). When it triggers, the broker places a limit order. A GTT
lasts until it triggers, is cancelled, or a year passes. The bot uses GTTs
for [broker-held stops on delivery positions](intraday-controls.md#exchange-held-stops).
The earlier implementation targeted a non-existent v2 endpoint with a
different payload, so it could never have placed an order. SELL GTTs
against delivery holdings need the account's eDIS or DDPI authorisation.

## Other operations

| Method | Purpose |
|---|---|
| `modify_order(order_id, quantity, price, order_type, trigger_price)` | Change a working order |
| `cancel_order(order_id)`, `cancel_all_orders()` | Cancel one / every open order |
| `place_gtt(symbol, side, qty, product, trigger, trigger_type)` | Good-till-triggered order on the v3 API ([GTT orders](#gtt-orders)) |
| `squareoff_all_mis()` | Close every open MIS position at the broker with market orders (live); no-op in paper |
| `place_basket_order(legs)` | Several option legs in sequence, each lot-snapped |
| `execute_options_signal(signal)` | Build legs from an options signal and place them as a basket |
| `fetch_broker_quantities()` | Net quantity per instrument from positions + holdings — raises on any API error |
| `get_positions()`, `get_holdings()`, `get_funds()`, `get_order_book()` | Account queries (return empty on error) |

After-market orders are supported through `UpstoxOrder.is_amo`.

## Smart order algorithms

`execution_engine/smart_order.py` provides algorithms for splitting a large
order over time. They produce schedules and track execution, but the bot does
not use them. The executor runs inside the tick loop, so an order spread over
minutes would stall ticks for every symbol. Slicing needs a background order
manager first, and at the default ₹5 lakh capital (at most ₹1 lakh per
position) it would rarely trigger. The [execution log](#execution-quality)
shows whether slippage makes it worth building.

| Class | Behaviour |
|---|---|
| `TWAPOrder` | Equal slices at fixed intervals |
| `VWAPOrder` | Slices weighted by the typical NSE intraday volume curve (heavier at the open and the last hour); `apply_participation_limit()` caps each slice at a share of actual market volume |
| `TransactionCostAnalyzer` | Post-trade analysis: slippage vs arrival price, market impact vs pre-trade VWAP, charges in basis points |

## Crypto executor

`execution_engine/executor.py` is the older generic executor for ccxt
exchanges (Binance), used only by the dormant crypto add-on. It still retries
order placement `execution.retry_attempts` times.
