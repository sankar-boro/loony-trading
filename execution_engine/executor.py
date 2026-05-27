from __future__ import annotations
import asyncio
import time
from typing import Dict, List, Optional, Callable
from strategies.base import Signal, SignalType
from risk_manager.risk_manager import RiskManager, Position
from .order import Order, OrderSide, OrderStatus, OrderType
from utils.logger import get_logger
from utils.timeutils import now_utc

logger = get_logger("execution")


class ExecutionEngine:
    """
    Smart order routing with slippage simulation, retry logic,
    partial fill handling, and latency budgeting.
    Supports live (ccxt exchange) and paper trading modes.
    """

    def __init__(self, cfg: dict, risk_manager: RiskManager,
                 exchange=None, mode: str = "paper"):
        self.cfg = cfg.get("execution", {})
        self.risk_manager = risk_manager
        self.exchange = exchange
        self.mode = mode  # live | paper
        self.order_history: List[Order] = []
        self._callbacks: List[Callable] = []
        self._slippage_pct = self.cfg.get("slippage_pct", 0.001)
        self._retry_attempts = self.cfg.get("retry_attempts", 3)
        self._retry_delay_ms = self.cfg.get("retry_delay_ms", 500)

    def on_fill(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    async def execute_signal(self, signal: Signal) -> Optional[Order]:
        if not self.risk_manager.validate_signal(signal):
            return None

        size = self.risk_manager.size_position(signal)
        if size <= 0:
            logger.warning(f"Zero size computed for {signal.symbol}")
            return None

        order_type = self._decide_order_type(signal)
        side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL

        order = Order(
            symbol=signal.symbol,
            side=side,
            order_type=order_type,
            quantity=size,
            price=signal.price if order_type == OrderType.LIMIT else None,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy=signal.strategy,
        )

        if self.mode == "paper":
            filled = await self._paper_fill(order, signal.price)
        else:
            filled = await self._live_fill(order)

        if filled:
            self.risk_manager.open_position(signal, size)
            self.order_history.append(order)
            for cb in self._callbacks:
                await cb(order) if asyncio.iscoroutinefunction(cb) else cb(order)

        return order

    async def close_position(self, pos: Position, current_price: float,
                               reason: str = "signal") -> Optional[Order]:
        side = OrderSide.SELL if pos.direction == 1 else OrderSide.BUY
        order = Order(
            symbol=pos.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=pos.size,
            price=current_price,
            strategy=pos.strategy,
        )

        if self.mode == "paper":
            await self._paper_fill(order, current_price)
        else:
            await self._live_fill(order)

        pnl = self.risk_manager.close_position(pos, order.avg_fill_price, reason)
        self.order_history.append(order)
        logger.info(f"Closed position {pos.symbol} reason={reason} pnl={pnl:.4f}")
        return order

    def _decide_order_type(self, signal: Signal) -> OrderType:
        order_type_cfg = self.cfg.get("order_type", "limit")
        if order_type_cfg == "smart":
            # Use market for high-confidence signals in volatile conditions
            return OrderType.MARKET if signal.confidence > 0.85 else OrderType.LIMIT
        return OrderType.LIMIT if order_type_cfg == "limit" else OrderType.MARKET

    async def _paper_fill(self, order: Order, market_price: float) -> bool:
        slippage = market_price * self._slippage_pct
        if order.side == OrderSide.BUY:
            fill_price = market_price + slippage
        else:
            fill_price = market_price - slippage

        order.avg_fill_price = fill_price
        order.filled_quantity = order.quantity
        order.commission = fill_price * order.quantity * 0.001
        order.status = OrderStatus.FILLED
        order.filled_at = now_utc().isoformat()
        logger.info(f"[PAPER] {order.side.value} {order.quantity:.6f} {order.symbol} "
                    f"@ {fill_price:.4f} slippage={slippage:.4f}")
        return True

    async def _live_fill(self, order: Order) -> bool:
        if self.exchange is None:
            logger.error("No exchange configured for live trading")
            return False

        for attempt in range(self._retry_attempts):
            try:
                t0 = time.monotonic()
                if order.order_type == OrderType.MARKET:
                    result = self.exchange.create_market_order(
                        order.symbol, order.side.value, order.quantity
                    )
                else:
                    result = self.exchange.create_limit_order(
                        order.symbol, order.side.value, order.quantity, order.price
                    )
                latency_ms = (time.monotonic() - t0) * 1000
                order.exchange_order_id = result.get("id", "")
                order.status = OrderStatus.OPEN
                logger.info(f"Order submitted exchange_id={order.exchange_order_id} "
                            f"latency={latency_ms:.1f}ms")
                # Poll for fill
                filled = await self._poll_fill(order)
                return filled
            except Exception as e:
                logger.error(f"Order attempt {attempt + 1} failed: {e}")
                if attempt < self._retry_attempts - 1:
                    await asyncio.sleep(self._retry_delay_ms / 1000)
        order.status = OrderStatus.REJECTED
        return False

    async def _poll_fill(self, order: Order, timeout_sec: float = 30) -> bool:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                result = self.exchange.fetch_order(order.exchange_order_id, order.symbol)
                if result["status"] == "closed":
                    order.avg_fill_price = result.get("average") or result.get("price", 0)
                    order.filled_quantity = result.get("filled", order.quantity)
                    order.status = OrderStatus.FILLED
                    order.filled_at = now_utc().isoformat()
                    return True
                if result["status"] == "canceled":
                    order.status = OrderStatus.CANCELLED
                    return False
            except Exception as e:
                logger.warning(f"Poll fill error: {e}")
            await asyncio.sleep(1)
        logger.warning(f"Fill timeout for order {order.exchange_order_id}")
        return False
