from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from utils.timeutils import now_utc


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: float | None = None        # None for market orders
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy: str = ""
    exchange_order_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    commission: float = 0.0
    created_at: str = field(default_factory=lambda: now_utc().isoformat())
    filled_at: str | None = None

    @property
    def is_done(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)

    @property
    def slippage(self) -> float:
        if self.price and self.avg_fill_price:
            return abs(self.avg_fill_price - self.price) / self.price
        return 0.0
