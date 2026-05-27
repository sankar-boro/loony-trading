import json
from pathlib import Path
from utils.timeutils import now_utc
from execution_engine.order import Order
from risk_manager.risk_manager import Position


class TradeLogger:
    """Appends trade events to a JSONL file for dashboard + analysis."""

    def __init__(self, log_dir: str = "logs"):
        self.path = Path(log_dir) / "trades.jsonl"
        self.path.parent.mkdir(exist_ok=True)

    def log_order(self, order: Order) -> None:
        record = {
            "ts": now_utc().isoformat(),
            "type": "order",
            "symbol": order.symbol,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "quantity": order.quantity,
            "price": order.avg_fill_price or order.price,
            "commission": order.commission,
            "status": order.status.value,
            "strategy": order.strategy,
        }
        self._append(record)

    def log_position_close(self, pos: Position, exit_price: float,
                            pnl: float, reason: str) -> None:
        record = {
            "ts": now_utc().isoformat(),
            "type": "close",
            "symbol": pos.symbol,
            "direction": pos.direction,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "size": pos.size,
            "pnl": pnl,
            "reason": reason,
            "strategy": pos.strategy,
        }
        self._append(record)

    def _append(self, record: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")
