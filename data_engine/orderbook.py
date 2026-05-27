import asyncio
from typing import Dict, Optional, Callable, List
from utils.logger import get_logger

logger = get_logger("orderbook")


class OrderBookSnapshot:
    def __init__(self, symbol: str, bids: list, asks: list, ts: int):
        self.symbol = symbol
        self.bids = bids  # [[price, size], ...]
        self.asks = asks
        self.ts = ts

    @property
    def best_bid(self) -> float:
        return self.bids[0][0] if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0][0] if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def spread_pct(self) -> float:
        return self.spread / self.mid_price if self.mid_price else 0.0

    def imbalance(self, depth: int = 10) -> float:
        """Order book imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol)"""
        bid_vol = sum(b[1] for b in self.bids[:depth])
        ask_vol = sum(a[1] for a in self.asks[:depth])
        total = bid_vol + ask_vol
        return (bid_vol - ask_vol) / total if total else 0.0

    def whale_pressure(self, threshold_usd: float = 100_000) -> float:
        """Net large-order direction (positive = buying pressure)."""
        large_bids = sum(b[0] * b[1] for b in self.bids if b[0] * b[1] >= threshold_usd)
        large_asks = sum(a[0] * a[1] for a in self.asks if a[0] * a[1] >= threshold_usd)
        total = large_bids + large_asks
        return (large_bids - large_asks) / total if total else 0.0


class OrderBookTracker:
    def __init__(self, exchange, symbols: List[str], depth: int = 20):
        self.exchange = exchange
        self.symbols = symbols
        self.depth = depth
        self._books: Dict[str, OrderBookSnapshot] = {}
        self._subscribers: List[Callable] = []
        self._running = False

    def subscribe(self, cb: Callable) -> None:
        self._subscribers.append(cb)

    def get(self, symbol: str) -> Optional[OrderBookSnapshot]:
        return self._books.get(symbol)

    async def start(self) -> None:
        self._running = True
        tasks = [self._track(sym) for sym in self.symbols]
        await asyncio.gather(*tasks)

    async def _track(self, symbol: str) -> None:
        while self._running:
            try:
                if hasattr(self.exchange, "watch_order_book"):
                    ob = await self.exchange.watch_order_book(symbol, self.depth)
                else:
                    ob = self.exchange.fetch_order_book(symbol, self.depth)
                snap = OrderBookSnapshot(
                    symbol=symbol,
                    bids=ob["bids"][:self.depth],
                    asks=ob["asks"][:self.depth],
                    ts=ob.get("timestamp") or 0,
                )
                self._books[symbol] = snap
                for cb in self._subscribers:
                    await cb(snap) if asyncio.iscoroutinefunction(cb) else cb(snap)
            except Exception as e:
                logger.error(f"OrderBook error {symbol}: {e}")
                await asyncio.sleep(2)

    async def stop(self) -> None:
        self._running = False
