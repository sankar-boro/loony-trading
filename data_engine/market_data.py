import asyncio
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Callable

from utils.logger import get_logger
from utils.timeutils import now_utc

logger = get_logger("data_engine")


class MarketDataEngine:
    """
    Ingests OHLCV data (historical + streaming) from ccxt-compatible exchanges.
    Caches locally and emits candle events to subscribers.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cache_dir = Path(cfg.get("data", {}).get("cache_dir", "./data/cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._exchanges: Dict[str, object] = {}
        self._candle_cache: Dict[str, Dict[str, pd.DataFrame]] = {}  # symbol -> tf -> df
        self._subscribers: List[Callable] = []
        self._running = False

    # ── Exchange setup ────────────────────────────────────────────────────────

    def init_exchange(self, exchange_id: str, api_key: str = "", api_secret: str = "",
                      sandbox: bool = True) -> None:
        import ccxt
        exchange_cls = getattr(ccxt, exchange_id)
        exchange = exchange_cls({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
        })
        if sandbox and hasattr(exchange, "set_sandbox_mode"):
            exchange.set_sandbox_mode(True)
        self._exchanges[exchange_id] = exchange
        logger.info(f"Initialized exchange: {exchange_id} (sandbox={sandbox})")

    # ── Historical data ───────────────────────────────────────────────────────

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h",
                    exchange_id: str = "binance",
                    lookback_days: int = 365) -> pd.DataFrame:
        cache_key = f"{exchange_id}_{symbol.replace('/', '_')}_{timeframe}"
        cache_file = self.cache_dir / f"{cache_key}.parquet"

        since = int((now_utc() - timedelta(days=lookback_days)).timestamp() * 1000)

        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            cached_end = int(df.index[-1].timestamp() * 1000)
            if cached_end >= since:
                logger.info(f"Loaded {symbol}/{timeframe} from cache ({len(df)} bars)")
                return df

        exchange = self._exchanges.get(exchange_id)
        if exchange is None:
            logger.warning(f"Exchange {exchange_id} not initialised; returning empty frame")
            return pd.DataFrame()

        all_bars = []
        while True:
            try:
                bars = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            except Exception as e:
                logger.error(f"fetch_ohlcv error: {e}")
                break
            if not bars:
                break
            all_bars.extend(bars)
            since = bars[-1][0] + 1
            if len(bars) < 1000:
                break

        if not all_bars:
            return pd.DataFrame()

        df = pd.DataFrame(all_bars, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df.set_index("ts", inplace=True)
        df = df[~df.index.duplicated(keep="last")]
        df.to_parquet(cache_file)

        self._candle_cache.setdefault(symbol, {})[timeframe] = df
        logger.info(f"Fetched {len(df)} bars for {symbol}/{timeframe}")
        return df

    def get_cached(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        return self._candle_cache.get(symbol, {}).get(timeframe)

    # ── Streaming ─────────────────────────────────────────────────────────────

    def subscribe(self, callback: Callable) -> None:
        self._subscribers.append(callback)

    async def start_streaming(self, symbols: List[str], timeframe: str = "1m",
                               exchange_id: str = "binance") -> None:
        self._running = True
        exchange = self._exchanges.get(exchange_id)
        if exchange is None or not hasattr(exchange, "watch_ohlcv"):
            logger.warning("Exchange does not support WebSocket streaming; falling back to polling")
            await self._poll_loop(symbols, timeframe, exchange_id)
            return

        tasks = [self._watch_symbol(exchange, sym, timeframe) for sym in symbols]
        await asyncio.gather(*tasks)

    async def _watch_symbol(self, exchange, symbol: str, timeframe: str) -> None:
        while self._running:
            try:
                candles = await exchange.watch_ohlcv(symbol, timeframe)
                for bar in candles:
                    event = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "ts": bar[0],
                        "open": bar[1],
                        "high": bar[2],
                        "low": bar[3],
                        "close": bar[4],
                        "volume": bar[5],
                    }
                    for cb in self._subscribers:
                        await cb(event) if asyncio.iscoroutinefunction(cb) else cb(event)
            except Exception as e:
                logger.error(f"Streaming error for {symbol}: {e}")
                await asyncio.sleep(5)

    async def _poll_loop(self, symbols: List[str], timeframe: str,
                          exchange_id: str, interval_sec: int = 60) -> None:
        exchange = self._exchanges[exchange_id]
        while self._running:
            for sym in symbols:
                try:
                    bars = exchange.fetch_ohlcv(sym, timeframe, limit=2)
                    if bars:
                        bar = bars[-1]
                        event = {
                            "symbol": sym, "timeframe": timeframe,
                            "ts": bar[0], "open": bar[1], "high": bar[2],
                            "low": bar[3], "close": bar[4], "volume": bar[5],
                        }
                        for cb in self._subscribers:
                            await cb(event) if asyncio.iscoroutinefunction(cb) else cb(event)
                except Exception as e:
                    logger.error(f"Poll error for {sym}: {e}")
            await asyncio.sleep(interval_sec)

    async def stop(self) -> None:
        self._running = False
