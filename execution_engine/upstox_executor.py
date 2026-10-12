"""
Upstox Execution Engine

Handles:
  - Regular orders (MARKET, LIMIT, SL, SL-M) for NSE/BSE equity + F&O
  - After-Market Orders (AMO)
  - Good Till Triggered (GTT) orders
  - Order modification and cancellation
  - Portfolio, positions, margins queries
  - Paper trading simulation with realistic Indian market slippage

Product types:
  CNC   - Cash & Carry (delivery equity, no leverage)
  MIS   - Margin Intraday Square-off (intraday, auto-squareoff 3:20 PM)
  NRML  - Normal (F&O carry-forward)

Order types:
  MARKET  - Market order
  LIMIT   - Limit order (requires price)
  SL      - Stop-Loss Limit (requires price + trigger_price)
  SL-M    - Stop-Loss Market (requires trigger_price only)
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable

from data_engine.upstox.auth import UpstoxAuth
from data_engine.upstox.instruments import InstrumentRegistry
from execution_engine.order import Order, OrderSide, OrderStatus, OrderType
from risk_manager.risk_manager import RiskManager, Position
from strategies.base import Signal, SignalType
from utils.logger import get_logger
from utils.timeutils import now_utc

logger = get_logger("upstox.execution")

_BASE_URL = "https://api.upstox.com/v2"


class UpstoxProduct(str, Enum):
    CNC  = "CNC"    # delivery
    MIS  = "MIS"    # intraday
    NRML = "NRML"   # F&O carry-forward


class UpstoxOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT  = "LIMIT"
    SL     = "SL"
    SL_M   = "SL-M"


class UpstoxValidity(str, Enum):
    DAY = "DAY"
    IOC = "IOC"


@dataclass
class UpstoxOrder:
    """Upstox-specific order record (extends the generic Order)."""
    instrument_key: str
    quantity:        int
    product:         UpstoxProduct
    order_type:      UpstoxOrderType
    transaction_type: str            # "BUY" | "SELL"
    price:           float = 0.0
    trigger_price:   float = 0.0
    validity:        UpstoxValidity = UpstoxValidity.DAY
    tag:             str = "loony"
    is_amo:          bool = False
    order_id:        str = ""
    status:          str = "pending"
    avg_price:       float = 0.0
    filled_qty:      int = 0
    exchange_order_id: str = ""
    created_at:      str = field(default_factory=lambda: now_utc().isoformat())

    @property
    def is_filled(self) -> bool:
        return self.status.upper() in ("COMPLETE", "FILLED")

    @property
    def is_rejected(self) -> bool:
        return self.status.upper() in ("REJECTED", "CANCELLED")


@dataclass
class GTTOrder:
    """Good Till Triggered order."""
    instrument_key:  str
    transaction_type: str
    quantity:        int
    product:         UpstoxProduct
    order_type:      UpstoxOrderType
    trigger_type:    str              # "single" | "two-leg"
    trigger_price:   float
    limit_price:     float
    gtt_id:          str = ""
    status:          str = "active"


class UpstoxExecutor:
    """
    Production-grade order executor for Upstox (Indian markets).
    Supports equity delivery (CNC), intraday (MIS), and F&O (NRML).
    Paper mode simulates realistic NSE/BSE fills with market impact.
    """

    def __init__(self, auth: UpstoxAuth, registry: InstrumentRegistry,
                 risk_manager: RiskManager, cfg: dict,
                 mode: str = "paper"):
        self.auth = auth
        self.registry = registry
        self.risk_manager = risk_manager
        self.cfg = cfg.get("execution", {})
        self.mode = mode
        self.order_history: List[UpstoxOrder] = []
        self._callbacks: List[Callable] = []
        self._slippage_pct = self.cfg.get("slippage_pct", 0.0005)  # 0.05% for NSE
        self._retry_attempts = self.cfg.get("retry_attempts", 3)
        self._session = None

        # India-specific defaults. `exchanges.upstox.default_product` is the
        # documented setting; `execution.upstox_product` still overrides it.
        self._default_product = UpstoxProduct(
            self.cfg.get("upstox_product")
            or cfg.get("exchanges", {}).get("upstox", {}).get("default_product", "CNC")
        )

    def on_fill(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    # ── HTTP session ──────────────────────────────────────────────────────────

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        self._session.headers.update({
            **self.auth.auth_header,
            "Content-Type": "application/json",
        })
        return self._session

    def _post(self, endpoint: str, payload: dict) -> dict:
        s = self._get_session()
        resp = s.post(f"{_BASE_URL}{endpoint}", json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _put(self, endpoint: str, payload: dict) -> dict:
        s = self._get_session()
        resp = s.put(f"{_BASE_URL}{endpoint}", json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, endpoint: str, params: dict) -> dict:
        s = self._get_session()
        resp = s.delete(f"{_BASE_URL}{endpoint}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        s = self._get_session()
        resp = s.get(f"{_BASE_URL}{endpoint}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ── Non-blocking wrappers ─────────────────────────────────────────────────
    # main.py's live loop and this executor's own async methods share one
    # asyncio event loop with the WebSocket tick stream. `requests` is
    # synchronous, so calling _post/_get/_put/_delete directly from an
    # `async def` blocks that entire loop for the HTTP round-trip —
    # delaying stop-loss checks and price updates for every OTHER open
    # position, not just the one placing an order. These run the same
    # synchronous call in a thread instead, off the event loop. See
    # docs/appendix/intraday-audit.md §4/§7 item 4.

    async def _post_async(self, endpoint: str, payload: dict) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._post, endpoint, payload)

    async def _get_async(self, endpoint: str, params: dict | None = None) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get, endpoint, params)

    async def _put_async(self, endpoint: str, payload: dict) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._put, endpoint, payload)

    async def _delete_async(self, endpoint: str, params: dict) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._delete, endpoint, params)

    # ── Signal execution ──────────────────────────────────────────────────────

    async def execute_signal(self, signal: Signal,
                              product: UpstoxProduct | None = None) -> Optional[UpstoxOrder]:
        if not self.risk_manager.validate_signal(signal):
            return None

        instrument_key = self._resolve_key(signal.symbol)
        if not instrument_key:
            logger.error(f"Cannot resolve instrument key for {signal.symbol}")
            return None

        lot_size = self.registry.get_lot_size(instrument_key)
        tick_size = self.registry.get_tick_size(instrument_key)
        size_float = self.risk_manager.size_position(signal)
        qty = max(lot_size, int(round(size_float / lot_size) * lot_size))
        qty = self._validate_quantity(instrument_key, qty, self.registry.get_lot_size(instrument_key))
        if qty <= 0:
            logger.warning(f"Zero qty for {signal.symbol}")
            return None

        prod = product or self._default_product
        tx = "BUY" if signal.signal_type == SignalType.BUY else "SELL"
        order_cfg = self.cfg.get("order_type", "limit")
        o_type = self._choose_order_type(signal, order_cfg)
        limit_price = self.registry.round_to_tick(signal.price, instrument_key)

        order = UpstoxOrder(
            instrument_key=instrument_key,
            quantity=qty,
            product=prod,
            order_type=o_type,
            transaction_type=tx,
            price=limit_price if o_type == UpstoxOrderType.LIMIT else 0.0,
            trigger_price=self.registry.round_to_tick(signal.stop_loss, instrument_key)
                          if o_type in (UpstoxOrderType.SL, UpstoxOrderType.SL_M) else 0.0,
            validity=UpstoxValidity.DAY,
            tag=f"loony-{signal.strategy[:20]}",
        )

        if self.mode == "paper":
            await self._paper_fill(order, signal.price)
        else:
            await self._live_place(order)
            if not order.is_filled and not order.is_rejected and order.order_id:
                # Still working after the status poll (e.g. an unfilled limit
                # order): cancel the rest so nothing can fill later untracked,
                # and track only what actually filled.
                await self.cancel_order(order.order_id)
                if order.filled_qty > 0:
                    logger.warning(f"Partial fill {order.filled_qty}/{qty} {signal.symbol} — "
                                   "remainder cancelled")
                    qty = order.filled_qty
                    order.status = "complete"
                else:
                    logger.info(f"Order {order.order_id} for {signal.symbol} not filled — cancelled")
                    order.status = "cancelled"

        if order.is_filled or self.mode == "paper":
            pos = self.risk_manager.open_position(signal, qty)
            if order.avg_price > 0:
                pos.entry_price = order.avg_price   # the actual fill, not the signal price
            self.order_history.append(order)
            for cb in self._callbacks:
                await cb(order) if asyncio.iscoroutinefunction(cb) else cb(order)
            logger.info(f"[{self.mode.upper()}] {tx} {qty} {signal.symbol} "
                        f"@ {order.avg_price:.2f} | {prod.value} | {signal.strategy}")

        return order

    # ── Order lifecycle ───────────────────────────────────────────────────────

    async def _live_place(self, order: UpstoxOrder) -> None:
        payload = {
            "quantity":         order.quantity,
            "product":          order.product.value,
            "validity":         order.validity.value,
            "price":            order.price,
            "tag":              order.tag,
            "instrument_token": order.instrument_key,
            "order_type":       order.order_type.value,
            "transaction_type": order.transaction_type,
            "disclosed_quantity": 0,
            "trigger_price":    order.trigger_price,
            "is_amo":           order.is_amo,
        }
        # One attempt only: placing an order is not idempotent. A request that
        # times out may still have reached the exchange, and a retry would
        # place a second, duplicate order. If that happens, the position shows
        # up at the broker and broker reconciliation (main.py) alerts on it.
        try:
            t0 = time.monotonic()
            resp = await self._post_async("/order/place", payload)
            latency_ms = (time.monotonic() - t0) * 1000
            order.order_id = resp.get("data", {}).get("order_id", "")
            order.status = "open"
            logger.info(f"Order placed: {order.order_id} latency={latency_ms:.1f}ms")
            await self._poll_order_status(order)
        except Exception as e:
            logger.error(f"Order placement failed (not retried — check the Upstox order book "
                         f"if this was a timeout): {e}")
            order.status = "rejected"

    async def _poll_order_status(self, order: UpstoxOrder,
                                  timeout_sec: float = 30) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                data = await self._get_async(f"/order/details",
                                              params={"order_id": order.order_id})
                o = data.get("data", {})
                order.status = o.get("status", "open").lower()
                order.avg_price = float(o.get("average_price", 0) or 0)
                order.filled_qty = int(o.get("filled_quantity", 0) or 0)
                order.exchange_order_id = o.get("exchange_order_id", "")
                if order.is_filled or order.is_rejected:
                    return
            except Exception as e:
                logger.warning(f"Poll status error: {e}")
            await asyncio.sleep(1)

    async def modify_order(self, order_id: str, quantity: int | None = None,
                            price: float | None = None,
                            order_type: UpstoxOrderType | None = None,
                            trigger_price: float | None = None,
                            validity: UpstoxValidity = UpstoxValidity.DAY) -> bool:
        payload = {"order_id": order_id, "validity": validity.value}
        if quantity is not None:
            payload["quantity"] = quantity
        if price is not None:
            payload["price"] = price
        if order_type is not None:
            payload["order_type"] = order_type.value
        if trigger_price is not None:
            payload["trigger_price"] = trigger_price
        try:
            await self._put_async("/order/modify", payload)
            logger.info(f"Order {order_id} modified")
            return True
        except Exception as e:
            logger.error(f"Modify order {order_id}: {e}")
            return False

    async def cancel_order(self, order_id: str) -> bool:
        try:
            await self._delete_async("/order/cancel", {"order_id": order_id})
            logger.info(f"Order {order_id} cancelled")
            return True
        except Exception as e:
            logger.error(f"Cancel order {order_id}: {e}")
            return False

    async def cancel_all_orders(self) -> int:
        orders = self.get_order_book()
        cancelled = 0
        for o in orders:
            if o.get("status", "").upper() not in ("COMPLETE", "REJECTED", "CANCELLED"):
                if await self.cancel_order(o["order_id"]):
                    cancelled += 1
        return cancelled

    # ── Close position ────────────────────────────────────────────────────────

    async def close_position(self, pos: Position, current_price: float,
                              reason: str = "signal") -> Optional[UpstoxOrder]:
        tx = "SELL" if pos.direction == 1 else "BUY"
        instrument_key = self._resolve_key(pos.symbol)
        if not instrument_key:
            return None

        lot_size = self.registry.get_lot_size(instrument_key)
        qty = max(lot_size, int(round(pos.size / lot_size) * lot_size))

        order = UpstoxOrder(
            instrument_key=instrument_key,
            quantity=qty,
            product=self._default_product,
            order_type=UpstoxOrderType.MARKET,
            transaction_type=tx,
            tag="loony-close",
        )

        if self.mode == "paper":
            await self._paper_fill(order, current_price)
        else:
            await self._live_place(order)

        pnl = self.risk_manager.close_position(pos, order.avg_price, reason)
        self.order_history.append(order)
        logger.info(f"Position closed: {pos.symbol} reason={reason} pnl={pnl:.2f}")
        return order

    # ── GTT Orders ────────────────────────────────────────────────────────────

    def place_gtt(self, symbol: str, transaction_type: str, quantity: int,
                   product: UpstoxProduct, trigger_price: float,
                   limit_price: float,
                   trigger_type: str = "single") -> Optional[GTTOrder]:
        """
        Place a Good Till Triggered order.
        GTT orders persist until triggered or manually cancelled.
        """
        instrument_key = self._resolve_key(symbol)
        if not instrument_key:
            return None
        payload = {
            "type":             trigger_type,
            "quantity":         quantity,
            "product":          product.value,
            "instrument_token": instrument_key,
            "transaction_type": transaction_type,
            "orders": [{
                "transaction_type": transaction_type,
                "quantity":         quantity,
                "product":          product.value,
                "order_type":       "LIMIT",
                "price":            limit_price,
            }],
            "condition": {
                "instrument_token": instrument_key,
                "exchange":         instrument_key.split("|")[0],
                "trigger_values":   [trigger_price],
                "last_traded_price": limit_price,
            }
        }
        try:
            resp = self._post("/order/gtt/place", payload)
            gtt_id = resp.get("data", {}).get("gtt_id", "")
            gtt = GTTOrder(
                instrument_key=instrument_key,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product,
                order_type=UpstoxOrderType.LIMIT,
                trigger_type=trigger_type,
                trigger_price=trigger_price,
                limit_price=limit_price,
                gtt_id=gtt_id,
            )
            logger.info(f"GTT placed: {symbol} trigger={trigger_price} gtt_id={gtt_id}")
            return gtt
        except Exception as e:
            logger.error(f"GTT place error {symbol}: {e}")
            return None

    def cancel_gtt(self, gtt_id: str) -> bool:
        try:
            self._delete("/order/gtt/cancel", {"gtt_id": gtt_id})
            return True
        except Exception as e:
            logger.error(f"GTT cancel error {gtt_id}: {e}")
            return False

    def get_gtt_orders(self) -> List[dict]:
        try:
            return self._get("/order/gtt/list").get("data", [])
        except Exception as e:
            logger.error(f"GTT list error: {e}")
            return []

    # ── Portfolio queries ─────────────────────────────────────────────────────

    def get_positions(self) -> List[dict]:
        """Short-term positions (intraday + F&O)."""
        try:
            return self._get("/portfolio/short-term-positions").get("data", [])
        except Exception as e:
            logger.error(f"Positions error: {e}")
            return []

    async def fetch_broker_quantities(self) -> tuple[dict[str, int], dict[str, int]]:
        """(total, today) net quantity per instrument key, for reconciliation.

        Unlike get_positions()/get_holdings(), this raises on any API failure:
        an error must never be mistaken for "the broker holds nothing"."""
        from execution_engine.reconcile import broker_net_quantities
        pos = await self._get_async("/portfolio/short-term-positions")
        hold = await self._get_async("/portfolio/long-term-holdings")
        for resp in (pos, hold):
            if resp.get("status") != "success":
                raise RuntimeError(f"Upstox portfolio API error: {resp.get('errors') or resp}")
        return broker_net_quantities(pos.get("data") or [], hold.get("data") or [])

    def get_holdings(self) -> List[dict]:
        """Long-term holdings (delivery equity)."""
        try:
            return self._get("/portfolio/long-term-holdings").get("data", [])
        except Exception as e:
            logger.error(f"Holdings error: {e}")
            return []

    def get_funds(self) -> dict:
        """Available margin/cash."""
        try:
            return self._get("/user/get-funds-and-margin").get("data", {})
        except Exception as e:
            logger.error(f"Funds error: {e}")
            return {}

    def get_order_book(self) -> List[dict]:
        """Today's order book."""
        try:
            return self._get("/order/retrieve-all").get("data", [])
        except Exception as e:
            logger.error(f"Order book error: {e}")
            return []

    def get_trade_book(self) -> List[dict]:
        """Today's executed trades."""
        try:
            return self._get("/order/trades/get-trades-for-day").get("data", [])
        except Exception as e:
            logger.error(f"Trade book error: {e}")
            return []

    def get_margins(self, orders: List[dict]) -> dict:
        """Calculate required margin for a basket of orders before placing."""
        try:
            return self._post("/charges/margin", {"orders": orders}).get("data", {})
        except Exception as e:
            logger.error(f"Margin calc error: {e}")
            return {}

    # ── NSE charge calculator ─────────────────────────────────────────────────

    @staticmethod
    def _compute_charges(price: float, qty: int, side: str, product: str) -> float:
        """
        Accurate NSE transaction costs for 2025.

        MIS round-trip ≈ 0.055%:
          brokerage ₹20 flat or 0.03% (whichever lower) + STT 0.025% sell
          + exchange charge 0.00345% + GST 18% + SEBI 0.0001% + stamp 0.003% buy

        CNC round-trip ≈ 0.21%:
          brokerage ₹0 (Upstox delivery free) + STT 0.1% both sides
          + exchange charge 0.00345% + GST 18% + SEBI 0.0001% + stamp 0.015% buy
        """
        value = price * qty
        is_mis = product in ("MIS", "NRML")

        if is_mis:
            brokerage  = min(20.0, value * 0.0003)
            stt        = value * 0.00025 if side == "SELL" else 0.0
            stamp_duty = value * 0.00003 if side == "BUY" else 0.0
        else:  # CNC delivery
            brokerage  = 0.0
            stt        = value * 0.001   # 0.1% on both sides
            stamp_duty = value * 0.00015 if side == "BUY" else 0.0

        exchange_charge = value * 0.0000345   # NSE transaction charge
        gst             = (brokerage + exchange_charge) * 0.18
        sebi_fee        = value * 0.000001    # ₹10 per crore

        return brokerage + stt + exchange_charge + gst + sebi_fee + stamp_duty

    # ── Paper fill simulation ─────────────────────────────────────────────────

    async def _paper_fill(self, order: UpstoxOrder, market_price: float) -> None:
        slippage = market_price * self._slippage_pct
        if order.transaction_type == "BUY":
            fill_price = market_price + slippage
        else:
            fill_price = market_price - slippage
        fill_price = round(fill_price, 2)

        total_charges = self._compute_charges(
            fill_price, order.quantity,
            order.transaction_type, order.product.value,
        )

        order.avg_price = fill_price
        order.filled_qty = order.quantity
        order.status = "complete"
        logger.info(f"[PAPER] {order.transaction_type} {order.quantity} "
                    f"{order.instrument_key.split('|')[-1]} @ ₹{fill_price:.2f} "
                    f"charges=₹{total_charges:.2f}")

    # ── Options basket execution ──────────────────────────────────────────────

    async def execute_options_signal(self, signal) -> list[str]:
        """
        Execute a multi-leg options signal (iron condor, straddle, etc.).
        Returns list of order_ids placed.
        """
        from data_engine.upstox.options_resolver import build_legs_from_signal
        from risk_manager.risk_manager import FO_LOT_SIZES

        legs = build_legs_from_signal(signal)
        if not legs:
            logger.warning(
                f"No legs resolved for {signal.symbol} "
                f"subtype={signal.metadata.get('strategy_subtype', '?')}"
            )
            return []

        lot = FO_LOT_SIZES.get(signal.symbol.upper(), 1)
        for leg in legs:
            leg["qty"] = lot   # one lot per leg by default

        return await self.place_basket_order(legs, tag=f"loony-{signal.strategy[:15]}")

    async def place_basket_order(self, legs: list[dict], tag: str = "loony") -> list[str]:
        """
        Place multiple option legs sequentially.
        Each leg: {instrument_key, action, qty, price, tag}.
        Returns list of order_ids (empty strings for paper fills).
        """
        order_ids: list[str] = []
        for leg in legs:
            instrument_key = leg["instrument_key"]
            qty   = self._validate_quantity(instrument_key, int(leg.get("qty", 1)),
                                            self.registry.get_lot_size(instrument_key))
            price = float(leg.get("price", 0.0))
            side  = leg.get("action", "BUY").upper()
            leg_tag = leg.get("tag", tag)

            order = UpstoxOrder(
                instrument_key=instrument_key,
                quantity=qty,
                product=UpstoxProduct.NRML,
                order_type=UpstoxOrderType.LIMIT if price > 0 else UpstoxOrderType.MARKET,
                transaction_type=side,
                price=price,
                tag=leg_tag,
            )

            if self.mode == "paper":
                await self._paper_fill(order, price or 1.0)
                order_ids.append("")
            else:
                try:
                    resp = await self._post_async("/order/place", {
                        "quantity":           order.quantity,
                        "product":            order.product.value,
                        "validity":           "DAY",
                        "price":              order.price,
                        "tag":                order.tag,
                        "instrument_token":   order.instrument_key,
                        "order_type":         order.order_type.value,
                        "transaction_type":   order.transaction_type,
                        "disclosed_quantity": 0,
                        "trigger_price":      0,
                        "is_amo":             False,
                    })
                    oid = resp.get("data", {}).get("order_id", "")
                    order_ids.append(oid)
                    logger.info(
                        f"Basket leg: {side} {qty} "
                        f"{instrument_key.split('|')[-1]} → order_id={oid}"
                    )
                except Exception as e:
                    logger.error(f"Basket leg failed ({instrument_key}): {e}")
                    order_ids.append("")

        return order_ids

    # ── MIS squareoff ─────────────────────────────────────────────────────────

    async def squareoff_all_mis(self) -> list[str]:
        """
        Close every open MIS (intraday) position with a market order.
        Called at 3:14 PM IST — before Upstox's forced squareoff at 3:20 PM.
        Returns list of symbols that were closed.
        """
        closed: list[str] = []

        if self.paper:
            # In paper mode, nothing to do via API — caller handles virtual positions
            logger.info("[PAPER] squareoff_all_mis called — no real orders to cancel")
            return closed

        positions = self.get_positions()
        for pos in positions:
            product = pos.get("product", "")
            qty = int(pos.get("quantity", 0))
            symbol = pos.get("trading_symbol", "")
            ikey   = pos.get("instrument_token", "")

            if product != "MIS" or qty == 0:
                continue

            # qty > 0 means long → close with SELL; qty < 0 means short → close with BUY
            txn_type = "SELL" if qty > 0 else "BUY"
            close_qty = abs(qty)

            order = UpstoxOrder(
                instrument_key=ikey or symbol,
                quantity=close_qty,
                product=UpstoxProduct.MIS,
                order_type=UpstoxOrderType.MARKET,
                transaction_type=txn_type,
                tag="mis_squareoff",
            )
            try:
                resp = await self._post_async("/order/place", {
                    "quantity":          order.quantity,
                    "product":           order.product.value,
                    "validity":          "DAY",
                    "price":             0,
                    "tag":               order.tag,
                    "instrument_token":  order.instrument_key,
                    "order_type":        order.order_type.value,
                    "transaction_type":  order.transaction_type,
                    "disclosed_quantity": 0,
                    "trigger_price":     0,
                    "is_amo":            False,
                })
                order_id = resp.get("data", {}).get("order_id", "")
                logger.info(
                    f"MIS squareoff: {txn_type} {close_qty} {symbol} "
                    f"(market) → order_id={order_id}"
                )
                closed.append(symbol)
            except Exception as e:
                logger.error(f"MIS squareoff failed for {symbol}: {e}")

        if closed:
            logger.info(f"MIS squareoff complete: {len(closed)} position(s) closed")
        else:
            logger.info("MIS squareoff: no open MIS positions found")

        return closed

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_key(self, symbol: str) -> Optional[str]:
        if "|" in symbol:
            return symbol
        return self.registry.get_key(symbol)

    @staticmethod
    def _validate_quantity(instrument_key: str, qty: int, master_lot: int = 1) -> int:
        """
        Snap F&O quantities down to a whole number of lots (at least one).
        Equity lot size is 1, so this is a no-op for equities.

        `master_lot` is the contract's lot_size from the instrument master —
        authoritative, since real F&O keys are numeric tokens
        ("NSE_FO|48906") that carry no underlying name. Without it, the
        underlying is parsed from a symbolic key and looked up in FO_LOT_SIZES.
        """
        from risk_manager.risk_manager import FO_LOT_SIZES
        if not (instrument_key.startswith("NSE_FO") or
                instrument_key.startswith("BSE_FO")):
            return qty
        raw = instrument_key.split("|")[-1]
        if master_lot > 1:
            snapped = max(master_lot, (qty // master_lot) * master_lot)
            if snapped != qty:
                logger.info(f"Qty snapped {qty}→{snapped} for {raw} (lot={master_lot})")
            return snapped
        # Symbolic key, e.g. "NSE_FO|NIFTY25JUN24500CE" → "NIFTY"
        underlying = raw.rstrip("0123456789").rstrip("CEPE")
        for name, lot in FO_LOT_SIZES.items():
            if underlying.startswith(name):
                snapped = max(lot, (qty // lot) * lot)
                if snapped != qty:
                    logger.info(f"Qty snapped {qty}→{snapped} for {raw} (lot={lot})")
                return snapped
        return qty

    @staticmethod
    def _choose_order_type(signal: Signal, cfg: str) -> UpstoxOrderType:
        if cfg == "market":
            return UpstoxOrderType.MARKET
        if cfg == "smart":
            return UpstoxOrderType.MARKET if signal.confidence > 0.85 else UpstoxOrderType.LIMIT
        return UpstoxOrderType.LIMIT
