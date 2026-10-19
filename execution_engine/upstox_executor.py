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
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable

from data_engine.upstox.auth import UpstoxAuth
from data_engine.upstox.instruments import InstrumentRegistry
from execution_engine.order import Order, OrderSide, OrderStatus, OrderType
from risk_manager.risk_manager import RiskManager, Position, can_open_short
from strategies.base import Signal, SignalType
from utils.logger import get_logger
from utils.timeutils import now_utc

logger = get_logger("upstox.execution")

_BASE_URL = "https://api.upstox.com/v2"
_V3_URL = "https://api.upstox.com/v3"          # GTT orders live on v3
_EXECUTION_LOG = Path(__file__).resolve().parent.parent / "logs" / "executions.jsonl"
_CLOSE_RETRY_SEC = 30                           # wait before re-sending a failed close


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
        self._close_failed_at: dict[str, float] = {}   # symbol → time of the last failed close
        # Limit-order chasing (live): re-price an unfilled limit toward the market
        self._chase_attempts = int(self.cfg.get("chase_attempts", 2))
        self._chase_wait_sec = float(self.cfg.get("chase_wait_sec", 10))
        self._max_chase_pct = float(self.cfg.get("max_chase_pct", 0.003))

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

    @staticmethod
    def _url(endpoint: str) -> str:
        return endpoint if endpoint.startswith("http") else f"{_BASE_URL}{endpoint}"

    def _post(self, endpoint: str, payload: dict) -> dict:
        s = self._get_session()
        resp = s.post(self._url(endpoint), json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _put(self, endpoint: str, payload: dict) -> dict:
        s = self._get_session()
        resp = s.put(self._url(endpoint), json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, endpoint: str, params: dict | None = None, body: dict | None = None) -> dict:
        s = self._get_session()
        resp = s.delete(self._url(endpoint), params=params, json=body, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        s = self._get_session()
        resp = s.get(self._url(endpoint), params=params, timeout=15)
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

    async def _delete_async(self, endpoint: str, params: dict | None = None,
                            body: dict | None = None) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._delete, endpoint, params, body)

    # ── Signal execution ──────────────────────────────────────────────────────

    async def execute_signal(self, signal: Signal,
                              product: UpstoxProduct | None = None,
                              quantity: int | None = None) -> Optional[UpstoxOrder]:
        """Validate, size, place and track one entry. `quantity` overrides the
        risk-based size (pair legs are sized to a hedge ratio)."""
        if not self.risk_manager.validate_signal(signal):
            return None

        instrument_key = self._resolve_key(signal.symbol)
        if not instrument_key:
            logger.error(f"Cannot resolve instrument key for {signal.symbol}")
            return None

        lot_size = self.registry.get_lot_size(instrument_key)
        tick_size = self.registry.get_tick_size(instrument_key)
        size_float = float(quantity) if quantity else self.risk_manager.size_position(signal)
        if size_float < lot_size:
            # Risk, exposure or sector limits leave room for less than one
            # lot: skip rather than round up to a lot nobody sized.
            logger.warning(f"{signal.symbol}: sized {size_float:.2f} < 1 lot ({lot_size}) — skipped")
            return None
        qty = int(size_float // lot_size) * lot_size
        qty = self._validate_quantity(instrument_key, qty, self.registry.get_lot_size(instrument_key))
        if qty <= 0:
            logger.warning(f"Zero qty for {signal.symbol}")
            return None

        prod = product or self._default_product
        if signal.signal_type == SignalType.SELL and not can_open_short(prod):
            logger.warning(f"Short entry in {signal.symbol} refused: {prod.value} does not allow "
                           "opening a short (use MIS for intraday shorts)")
            return None
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

        t0 = time.monotonic()
        limit0, chases = order.price, 0
        if self.mode == "paper":
            await self._paper_fill(order, signal.price)
        else:
            await self._live_place(order)
            if (not order.is_filled and not order.is_rejected and order.order_id
                    and order.order_type == UpstoxOrderType.LIMIT):
                chases = await self._chase(order, instrument_key)
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

        self._log_execution("entry", order, signal.symbol, signal.strategy, signal.price,
                            limit0, qty, chases, t0)
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

    async def _ltp(self, instrument_key: str) -> float | None:
        """Last traded price from the quote API (None on any failure)."""
        try:
            data = await self._get_async("/market-quote/ltp", params={"instrument_key": instrument_key})
            for v in (data.get("data") or {}).values():
                if v.get("last_price"):
                    return float(v["last_price"])
        except Exception as e:
            logger.debug(f"LTP {instrument_key}: {e}")
        return None

    async def _chase(self, order: UpstoxOrder, instrument_key: str) -> int:
        """A limit order still working after the first poll is re-priced toward
        the market up to `execution.chase_attempts` times, never further than
        `max_chase_pct` from its original price, waiting `chase_wait_sec`
        after each change. Returns how many times it was re-priced."""
        side = 1 if order.transaction_type == "BUY" else -1
        start = order.price
        cap = start * (1 + side * self._max_chase_pct)
        tick = self.registry.get_tick_size(instrument_key) or 0.05
        chases = 0
        for _ in range(self._chase_attempts):
            ltp = await self._ltp(instrument_key)
            target = ltp if ltp else order.price * (1 + side * self._max_chase_pct / max(self._chase_attempts, 1))
            new = min(max(target, order.price + tick), cap) if side == 1 else max(min(target, order.price - tick), cap)
            new = self.registry.round_to_tick(new, instrument_key)
            if (new - order.price) * side < tick / 2:
                break                                   # already at the cap
            if not await self.modify_order(order.order_id, price=new):
                break
            order.price = new
            chases += 1
            logger.info(f"Chasing {order.order_id}: limit {start:.2f} → {new:.2f}")
            await self._poll_order_status(order, timeout_sec=self._chase_wait_sec)
            if order.is_filled or order.is_rejected:
                break
        return chases

    def _log_execution(self, kind: str, order: UpstoxOrder, symbol: str, strategy: str,
                       decision_price: float, limit_price: float, qty: int, chases: int,
                       t0: float) -> None:
        """One line per order in logs/executions.jsonl for the execution-quality
        report: decision vs fill price, outcome, chases, latency."""
        import json
        from utils.timeutils import now_ist
        filled = order.filled_qty or (order.quantity if order.is_filled else 0)
        side = 1 if order.transaction_type == "BUY" else -1
        fill = order.avg_price if filled else None
        rec = {
            "ts": now_ist().isoformat(timespec="seconds"), "mode": self.mode, "kind": kind,
            "symbol": symbol, "strategy": strategy, "side": order.transaction_type,
            "order_type": order.order_type.value, "product": order.product.value,
            "qty": qty, "filled_qty": filled, "decision_price": decision_price,
            "limit_price": limit_price or None, "fill_price": fill,
            "slippage_bps": (round(side * (fill - decision_price) / decision_price * 1e4, 2)
                             if fill and decision_price else None),
            "outcome": ("filled" if filled >= qty else "partial" if filled else
                        "unfilled" if order.status == "cancelled" or not order.is_rejected
                        else "rejected"),
            "chases": chases, "latency_ms": round((time.monotonic() - t0) * 1000),
        }
        try:
            _EXECUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _EXECUTION_LOG.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError as e:
            logger.warning(f"Could not write execution log: {e}")

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

    # ── Exchange-held stops ───────────────────────────────────────────────────
    # A stop that lives only inside the bot protects nothing if the bot or its
    # network dies. These keep an SL-M order at the broker for each live
    # position, moved with the trailing stop (intraday.exchange_stops).

    def _uses_gtt(self) -> bool:
        """Delivery positions are held overnight, and a DAY stop order expires at
        the close — so on CNC the broker stop is a GTT, which persists."""
        return self._default_product == UpstoxProduct.CNC

    @staticmethod
    def _is_gtt(stop_id: str) -> bool:
        return stop_id.startswith("GTT-")

    async def place_exchange_stop(self, pos: Position) -> str:
        """Live: protect the position with a broker-held stop at pos.stop_loss —
        an SL-M DAY order on MIS, a GTT on CNC (it survives the close).
        Records the id on the position; returns it, or "" on failure / paper."""
        if self.mode != "live":
            return ""
        instrument_key = self._resolve_key(pos.symbol)
        if not instrument_key:
            return ""
        trigger = self.registry.round_to_tick(pos.stop_loss, instrument_key)
        if self._uses_gtt():
            loop = asyncio.get_running_loop()
            gtt = await loop.run_in_executor(
                None, lambda: self.place_gtt(pos.symbol, "SELL" if pos.direction == 1 else "BUY",
                                             int(round(pos.size)), self._default_product, trigger,
                                             "BELOW" if pos.direction == 1 else "ABOVE"))
            if gtt and gtt.gtt_id:
                pos.stop_order_id, pos.stop_synced = gtt.gtt_id, trigger
                return gtt.gtt_id
            logger.error(f"Could not place GTT stop for {pos.symbol} (SELL GTTs on delivery "
                         "holdings need eDIS/DDPI authorisation on the account)")
            return ""
        payload = {
            "quantity":         int(round(pos.size)),
            "product":          self._default_product.value,
            "validity":         UpstoxValidity.DAY.value,
            "price":            0,
            "tag":              "loony-stop",
            "instrument_token": instrument_key,
            "order_type":       UpstoxOrderType.SL_M.value,
            "transaction_type": "SELL" if pos.direction == 1 else "BUY",
            "disclosed_quantity": 0,
            "trigger_price":    trigger,
            "is_amo":           False,
        }
        try:
            resp = await self._post_async("/order/place", payload)
            pos.stop_order_id = resp.get("data", {}).get("order_id", "")
            pos.stop_synced = trigger
            logger.info(f"Exchange stop {pos.stop_order_id} for {pos.symbol} @ {trigger}")
            return pos.stop_order_id
        except Exception as e:
            logger.error(f"Could not place exchange stop for {pos.symbol}: {e}")
            return ""

    async def sync_exchange_stop(self, pos: Position, min_move_pct: float = 0.001) -> bool:
        """Move the exchange stop to pos.stop_loss once it has moved at least
        min_move_pct (and a tick) from the last trigger sent."""
        if not pos.stop_order_id:
            return False
        instrument_key = self._resolve_key(pos.symbol) or pos.symbol
        trigger = self.registry.round_to_tick(pos.stop_loss, instrument_key)
        tick = self.registry.get_tick_size(instrument_key) or 0.05
        if abs(trigger - pos.stop_synced) < max(tick, pos.stop_synced * min_move_pct):
            return False
        if self._is_gtt(pos.stop_order_id):
            loop = asyncio.get_running_loop()
            ok = await loop.run_in_executor(
                None, lambda: self.modify_gtt(pos.stop_order_id, int(round(pos.size)), trigger,
                                              "BELOW" if pos.direction == 1 else "ABOVE"))
            if ok:
                pos.stop_synced = trigger
            return ok
        if await self.modify_order(pos.stop_order_id, trigger_price=trigger,
                                   order_type=UpstoxOrderType.SL_M):
            pos.stop_synced = trigger
            return True
        return False

    async def exchange_stop_status(self, pos: Position) -> dict:
        """{"status", "avg_price", "filled_qty"} of the position's exchange stop;
        {} if there is none or the lookup fails."""
        if not pos.stop_order_id:
            return {}
        if self._is_gtt(pos.stop_order_id):
            return await self._gtt_stop_status(pos)
        try:
            data = await self._get_async("/order/details", params={"order_id": pos.stop_order_id})
            o = data.get("data", {})
            return {"status": str(o.get("status", "")).lower(),
                    "avg_price": float(o.get("average_price", 0) or 0),
                    "filled_qty": int(o.get("filled_quantity", 0) or 0)}
        except Exception as e:
            logger.warning(f"Exchange stop status {pos.stop_order_id}: {e}")
            return {}

    async def _gtt_stop_status(self, pos: Position) -> dict:
        """Status of a GTT stop in the same shape as an order's. A triggered GTT
        reports its generated order's status and fill. The API stops listing a
        GTT once it completes, so a GTT that has vanished is resolved against
        the broker's holdings: if the position is gone, the stop executed."""
        loop = asyncio.get_running_loop()
        try:
            gtt = await loop.run_in_executor(None, self.get_gtt, pos.stop_order_id)
        except Exception:
            return {}
        if gtt is None:
            key = self._resolve_key(pos.symbol)
            try:
                total, _ = await self.fetch_broker_quantities()
            except Exception as e:
                logger.warning(f"GTT {pos.stop_order_id} gone and holdings unavailable: {e}")
                return {}
            held = total.get(key, 0) * pos.direction
            if held < pos.size:
                return {"status": "complete", "avg_price": pos.stop_synced, "filled_qty": int(pos.size)}
            return {"status": "cancelled", "avg_price": 0.0, "filled_qty": 0}
        rule = (gtt.get("rules") or [{}])[0]
        status = str(rule.get("status", "")).upper()
        if status in ("TRIGGERED", "COMPLETED", "OPEN") and rule.get("order_id"):
            data = await self._get_async("/order/details", params={"order_id": rule["order_id"]})
            o = data.get("data", {})
            return {"status": str(o.get("status", "")).lower(),
                    "avg_price": float(o.get("average_price", 0) or 0),
                    "filled_qty": int(o.get("filled_quantity", 0) or 0)}
        return {"status": status.lower(), "avg_price": 0.0, "filled_qty": 0}

    async def cancel_exchange_stop(self, pos: Position) -> bool:
        if not pos.stop_order_id:
            return True
        if self._is_gtt(pos.stop_order_id):
            status = await self._gtt_stop_status(pos)
            if status.get("status") == "cancelled":       # already gone at the broker
                pos.stop_order_id = ""
                return True
            loop = asyncio.get_running_loop()
            ok = await loop.run_in_executor(None, self.cancel_gtt, pos.stop_order_id)
            if ok:
                pos.stop_order_id = ""
            return ok
        ok = await self.cancel_order(pos.stop_order_id)
        if ok:
            pos.stop_order_id = ""
        return ok

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

        t0 = time.monotonic()
        if self.mode == "paper":
            await self._paper_fill(order, current_price)
        else:
            last_fail = self._close_failed_at.get(pos.symbol, 0.0)
            if time.monotonic() - last_fail < _CLOSE_RETRY_SEC:
                return None                     # a close just failed; don't hammer the broker
            await self._live_place(order)
        self._log_execution("exit", order, pos.symbol, pos.strategy, current_price, 0.0,
                            qty, 0, t0)
        if self.mode != "paper" and not (order.is_filled and order.avg_price > 0):
            # Never book a close that did not happen: a rejected or failed
            # market order used to close the position at ₹0 in the books while
            # it stayed open at the broker.
            self._close_failed_at[pos.symbol] = time.monotonic()
            logger.error(f"Close of {pos.symbol} ({reason}) not filled (status {order.status}) — "
                         f"position kept; retrying in {_CLOSE_RETRY_SEC}s")
            return None
        self._close_failed_at.pop(pos.symbol, None)

        pnl = self.risk_manager.close_position(pos, order.avg_price, reason)
        self.order_history.append(order)
        logger.info(f"Position closed: {pos.symbol} reason={reason} pnl={pnl:.2f}")
        return order

    # ── GTT Orders ────────────────────────────────────────────────────────────

    # Upstox v3 GTT API (documented at upstox.com/developer/api-documentation/
    # place-gtt-order, checked 2026-10-19). A GTT stays at the broker until it
    # triggers, is cancelled, or a year passes — unlike a DAY stop order, it
    # survives the close, so it protects delivery (CNC) positions overnight.
    # SELL GTTs on delivery holdings need the account's eDIS/DDPI authorisation.
    _GTT_PRODUCT = {"CNC": "D", "MIS": "I"}

    def _gtt_payload(self, instrument_key: str, transaction_type: str, quantity: int,
                     product: UpstoxProduct, trigger_price: float, trigger_type: str) -> dict:
        return {
            "type": "SINGLE", "quantity": int(quantity),
            "product": self._GTT_PRODUCT.get(product.value, "D"),
            "instrument_token": instrument_key, "transaction_type": transaction_type,
            "rules": [{"strategy": "ENTRY", "trigger_type": trigger_type,
                       "trigger_price": float(trigger_price)}],
        }

    def place_gtt(self, symbol: str, transaction_type: str, quantity: int,
                  product: UpstoxProduct, trigger_price: float,
                  trigger_type: str = "BELOW") -> Optional[GTTOrder]:
        """Place a single-leg GTT: when the price crosses `trigger_price` in the
        `trigger_type` direction (ABOVE/BELOW), the broker places a limit order."""
        instrument_key = self._resolve_key(symbol)
        if not instrument_key:
            return None
        payload = self._gtt_payload(instrument_key, transaction_type, quantity, product,
                                    trigger_price, trigger_type)
        try:
            resp = self._post(f"{_V3_URL}/order/gtt/place", payload)
            ids = (resp.get("data") or {}).get("gtt_order_ids") or []
            gtt_id = ids[0] if ids else ""
            logger.info(f"GTT placed: {symbol} {transaction_type} {trigger_type} {trigger_price} id={gtt_id}")
            return GTTOrder(instrument_key=instrument_key, transaction_type=transaction_type,
                            quantity=quantity, product=product, order_type=UpstoxOrderType.LIMIT,
                            trigger_type=trigger_type, trigger_price=trigger_price,
                            limit_price=0.0, gtt_id=gtt_id)
        except Exception as e:
            logger.error(f"GTT place error {symbol}: {e}")
            return None

    def modify_gtt(self, gtt_id: str, quantity: int, trigger_price: float,
                   trigger_type: str = "BELOW") -> bool:
        try:
            self._put(f"{_V3_URL}/order/gtt/modify", {
                "type": "SINGLE", "quantity": int(quantity), "gtt_order_id": gtt_id,
                "rules": [{"strategy": "ENTRY", "trigger_type": trigger_type,
                           "trigger_price": float(trigger_price)}]})
            return True
        except Exception as e:
            logger.error(f"GTT modify error {gtt_id}: {e}")
            return False

    def cancel_gtt(self, gtt_id: str) -> bool:
        try:
            self._delete(f"{_V3_URL}/order/gtt/cancel", body={"gtt_order_id": gtt_id})
            return True
        except Exception as e:
            logger.error(f"GTT cancel error {gtt_id}: {e}")
            return False

    def get_gtt(self, gtt_id: str) -> Optional[dict]:
        """The GTT's details, or None if the broker no longer lists it (the
        API does not return completed GTTs)."""
        try:
            rows = self._get(f"{_V3_URL}/order/gtt", params={"gtt_order_id": gtt_id}).get("data") or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning(f"GTT details {gtt_id}: {e}")
            raise

    def get_gtt_orders(self) -> List[dict]:
        try:
            return self._get(f"{_V3_URL}/order/gtt").get("data", []) or []
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
