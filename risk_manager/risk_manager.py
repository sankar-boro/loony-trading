from __future__ import annotations
import math
from dataclasses import asdict, dataclass, field, fields
from typing import Dict, List, Optional
from strategies.base import Signal, SignalType
from utils.logger import get_logger
from utils.math_utils import safe_divide

logger = get_logger("risk_manager")

# NSE/BSE F&O lot sizes (as of 2025). Must keep in sync with exchange circulars.
FO_LOT_SIZES: dict[str, int] = {
    "NIFTY":       75,
    "BANKNIFTY":   30,
    "FINNIFTY":    65,
    "MIDCPNIFTY":  75,
    "SENSEX":      10,
    "BANKEX":      15,
}


def snap_to_lot(symbol: str, quantity: float) -> int:
    """Round quantity down to the nearest valid F&O lot size. Equity lot size is 1."""
    lot = FO_LOT_SIZES.get(symbol.upper().split("|")[-1][:10], 1)
    snapped = max(lot, int(quantity // lot) * lot)
    return snapped


@dataclass
class Position:
    symbol: str
    direction: int          # 1=long, -1=short
    entry_price: float
    size: float             # quantity of asset
    stop_loss: float
    take_profit: float
    trailing_stop_pct: float
    strategy: str
    peak_price: float = 0.0
    pnl: float = 0.0
    entry_time: str = ""     # ISO timestamp, set when the position is opened

    def update_trailing_stop(self, current_price: float) -> None:
        if self.direction == 1 and current_price > self.peak_price:
            self.peak_price = current_price
            self.stop_loss = max(
                self.stop_loss,
                self.peak_price * (1 - self.trailing_stop_pct),
            )
        elif self.direction == -1 and (self.peak_price == 0 or current_price < self.peak_price):
            self.peak_price = current_price
            self.stop_loss = min(
                self.stop_loss,
                self.peak_price * (1 + self.trailing_stop_pct),
            )

    def should_stop(self, current_price: float) -> bool:
        if self.direction == 1:
            return current_price <= self.stop_loss
        return current_price >= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        if self.direction == 1:
            return current_price >= self.take_profit
        return current_price <= self.take_profit

    @property
    def unrealised_pnl(self) -> float:
        return self.pnl

    def mark(self, current_price: float) -> float:
        self.pnl = (current_price - self.entry_price) * self.direction * self.size
        return self.pnl


class RiskManager:
    """
    Validates signals, sizes positions, and monitors open trades.
    """

    def __init__(self, cfg: dict, initial_capital: float):
        self.cfg = cfg.get("risk", {})
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.positions: Dict[str, List[Position]] = {}   # symbol -> positions
        self.daily_pnl = 0.0
        self.daily_trade_count = 0
        self.version = 0   # bumped on every open/close, so callers know when to persist

    # ── Signal validation ─────────────────────────────────────────────────────

    def validate_signal(self, signal: Signal) -> bool:
        """Returns False if the trade should be rejected."""
        max_concurrent = self.cfg.get("max_concurrent_trades", 10)
        total_open = sum(len(v) for v in self.positions.values())
        if total_open >= max_concurrent:
            logger.warning(f"Max concurrent trades reached ({max_concurrent})")
            return False

        max_dd = self.cfg.get("max_daily_drawdown", 0.05)
        if self.daily_pnl < -self.capital * max_dd:
            logger.warning("Max daily drawdown hit — blocking new trades")
            return False

        if signal.confidence < 0.5:
            logger.debug(f"Signal confidence too low: {signal.confidence:.2f}")
            return False

        # One position per symbol: never pyramid into the same direction, and
        # never open the other way on top of an open position (close it first).
        if self.positions.get(signal.symbol):
            logger.debug(f"Position already open in {signal.symbol} — signal ignored")
            return False

        return True

    # ── Position sizing ────────────────────────────────────────────────────────

    def size_position(self, signal: Signal) -> float:
        """Returns position size in base currency units (quantity)."""
        risk_pct = self.cfg.get("max_risk_per_trade", 0.01)
        risk_amount = self.capital * risk_pct

        price = signal.price
        stop_loss = signal.stop_loss
        risk_per_unit = abs(price - stop_loss)

        if risk_per_unit <= 0:
            logger.warning("Invalid stop loss distance — using fallback sizing")
            return risk_amount / price * 0.01

        if self.cfg.get("use_kelly_criterion", False):
            size = self._kelly_size(signal, risk_per_unit)
        else:
            size = risk_amount / risk_per_unit

        # Cap to max portfolio risk
        max_exposure_pct = self.cfg.get("max_portfolio_risk", 0.20)
        max_size = self.capital * max_exposure_pct / price
        size = min(size, max_size)

        return round(size, 8)

    def _kelly_size(self, signal: Signal, risk_per_unit: float) -> float:
        win_prob = signal.confidence
        rr = abs(signal.take_profit - signal.price) / max(risk_per_unit, 1e-9)
        kelly = win_prob - (1 - win_prob) / rr
        fraction = self.cfg.get("kelly_fraction", 0.25)
        kelly_risk = max(kelly * fraction, 0) * self.capital
        return kelly_risk / risk_per_unit

    # ── Position management ────────────────────────────────────────────────────

    def open_position(self, signal: Signal, size: float) -> Position:
        pos = Position(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.price,
            size=size,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            trailing_stop_pct=self.cfg.get("trailing_stop_pct", 0.02),
            strategy=signal.strategy,
            peak_price=signal.price,
            entry_time=signal.ts,
        )
        self.positions.setdefault(signal.symbol, []).append(pos)
        self.daily_trade_count += 1
        self.version += 1
        logger.info(f"Position opened: {signal.symbol} {signal.signal_type.value} "
                    f"size={size:.6f} entry={signal.price} SL={signal.stop_loss:.4f}")
        return pos

    def close_position(self, pos: Position, current_price: float,
                        reason: str = "signal") -> float:
        pnl = pos.mark(current_price)
        self.capital += pnl
        self.daily_pnl += pnl
        symbol = pos.symbol
        if symbol in self.positions and pos in self.positions[symbol]:
            self.positions[symbol].remove(pos)
        self.version += 1
        logger.info(f"Position closed: {symbol} pnl={pnl:.4f} reason={reason}")
        return pnl

    def update_all(self, prices: Dict[str, float]) -> List[tuple[Position, str]]:
        """Check stop/TP for all open positions. Returns list of (position, reason) to close."""
        to_close = []
        for symbol, pos_list in self.positions.items():
            price = prices.get(symbol)
            if price is None:
                continue
            for pos in list(pos_list):
                pos.update_trailing_stop(price)
                pos.mark(price)
                if pos.should_stop(price):
                    to_close.append((pos, "stop_loss"))
                elif pos.should_take_profit(price):
                    to_close.append((pos, "take_profit"))
        return to_close

    # ── Persistence ────────────────────────────────────────────────────────────

    def to_state(self) -> dict:
        return {
            "capital": self.capital,
            "daily_pnl": self.daily_pnl,
            "daily_trade_count": self.daily_trade_count,
            "positions": [asdict(p) for lst in self.positions.values() for p in lst],
        }

    def restore_positions(self, rows: list[dict]) -> int:
        """Re-create open positions from saved rows (unknown keys are ignored)."""
        known = {f.name for f in fields(Position)}
        for row in rows:
            pos = Position(**{k: v for k, v in row.items() if k in known})
            self.positions.setdefault(pos.symbol, []).append(pos)
        self.version += 1
        return len(rows)

    def reset_daily(self) -> None:
        self.daily_pnl = 0.0
        self.daily_trade_count = 0

    @property
    def open_count(self) -> int:
        return sum(len(v) for v in self.positions.values())

    @property
    def total_exposure(self) -> float:
        total = 0.0
        for pos_list in self.positions.values():
            for pos in pos_list:
                total += pos.size * pos.entry_price
        return total
