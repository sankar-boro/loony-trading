"""
Upstox Data Engine

Provides:
  - Historical OHLCV candles (1min to monthly, up to 2 years)
  - Real-time quotes (LTP, OHLC, depth)
  - Full market depth (bid/ask levels)
  - Intraday candle streaming via polling
  - Parquet cache identical to the ccxt-based MarketDataEngine
"""
from __future__ import annotations
import time
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Callable

import pandas as pd

from .auth import UpstoxAuth
from .instruments import InstrumentRegistry
from utils.logger import get_logger
from utils.timeutils import now_utc
from .corporate_actions import load_actions, apply_adjustments

logger = get_logger("upstox.data")

_BASE_URL = "https://api.upstox.com/v2"

# Upstox interval names mapped from our internal convention
_TF_MAP = {
    "1m":    "1minute",
    "1min":  "1minute",
    "3m":    "3minute",
    "5m":    "5minute",
    "10m":   "10minute",
    "15m":   "15minute",
    "30m":   "30minute",
    "1h":    "30minute",   # Upstox has no 1h; use 30m and resample
    "60m":   "60minute",
    "2h":    "120minute",
    "4h":    "240minute",
    "1d":    "day",
    "D":     "day",
    "1w":    "week",
    "W":     "week",
    "1M":    "month",
    "M":     "month",
}

# Max lookback per interval (Upstox hard limits)
_MAX_LOOKBACK_DAYS = {
    "1minute":   100,
    "3minute":   100,
    "5minute":   100,
    "10minute":  100,
    "15minute":  200,
    "30minute":  200,
    "60minute":  200,
    "120minute": 200,
    "240minute": 400,
    "day":       2000,
    "week":      2000,
    "month":     2000,
}


class UpstoxDataEngine:
    """
    Primary data engine for Indian markets.
    Compatible API surface with MarketDataEngine so strategies/backtester
    require zero changes.
    """

    def __init__(self, auth: UpstoxAuth, registry: InstrumentRegistry,
                 cache_dir: str = "data/cache",
                 adjust_prices: bool = True):
        self.auth = auth
        self.registry = registry
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._candle_cache: Dict[str, Dict[str, pd.DataFrame]] = {}
        self._subscribers: List[Callable] = []
        self._running = False
        self._session = None   # requests.Session, lazy init
        self._adjust_prices = adjust_prices
        self._corp_actions: dict | None = None  # loaded lazily

    # ── HTTP session ──────────────────────────────────────────────────────────

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        self._session.headers.update(self.auth.auth_header)
        return self._session

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        s = self._get_session()
        url = f"{_BASE_URL}{endpoint}"
        resp = s.get(url, params=params, timeout=15)
        if resp.status_code == 401:
            raise PermissionError("Upstox token invalid or expired — re-authenticate")
        resp.raise_for_status()
        return resp.json()

    # ── Historical OHLCV ──────────────────────────────────────────────────────

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1d",
                     lookback_days: int = 365) -> pd.DataFrame:
        """
        Fetch OHLCV bars for an instrument.

        Args:
            symbol: Trading symbol e.g. "RELIANCE", "NIFTY50", or raw
                    instrument_key e.g. "NSE_EQ|INE002A01018"
            timeframe: Internal timeframe ("1m", "15m", "1h", "1d", ...)
            lookback_days: How many days back to fetch

        Returns:
            pd.DataFrame with columns [open, high, low, close, volume]
            indexed by UTC datetime.
        """
        instrument_key = self._resolve_key(symbol)
        if not instrument_key:
            logger.error(f"Unknown symbol: {symbol}")
            return pd.DataFrame()

        upstox_interval = _TF_MAP.get(timeframe, "day")
        max_days = _MAX_LOOKBACK_DAYS.get(upstox_interval, 365)
        lookback_days = min(lookback_days, max_days)

        cache_key = f"upstox_{symbol.replace('|', '_')}_{timeframe}"
        cache_file = self.cache_dir / f"{cache_key}.parquet"

        # Load cache if fresh enough (< 1 day for intraday, < 7 days for daily+)
        cache_threshold_hours = 1 if "minute" in upstox_interval else 12
        if cache_file.exists():
            age_h = (time.time() - cache_file.stat().st_mtime) / 3600
            if age_h < cache_threshold_hours:
                df = pd.read_parquet(cache_file)
                logger.info(f"Cache hit: {symbol}/{timeframe} ({len(df)} bars, {age_h:.1f}h old)")
                self._candle_cache.setdefault(symbol, {})[timeframe] = df
                return df

        # Fetch in chunks if needed (Upstox has per-request date range limits)
        end_dt = now_utc()
        start_dt = end_dt - timedelta(days=lookback_days)
        all_frames = []

        # Upstox historical endpoint allows up to 30 days per call for 1min
        chunk_days = 30 if "minute" in upstox_interval else lookback_days
        cursor = start_dt
        while cursor < end_dt:
            chunk_end = min(cursor + timedelta(days=chunk_days), end_dt)
            df_chunk = self._fetch_chunk(instrument_key, upstox_interval, cursor, chunk_end)
            if not df_chunk.empty:
                all_frames.append(df_chunk)
            cursor = chunk_end + timedelta(seconds=1)
            if chunk_days >= lookback_days:
                break

        if not all_frames:
            logger.warning(f"No data returned for {symbol}/{timeframe}")
            return pd.DataFrame()

        df = pd.concat(all_frames).sort_index()
        df = df[~df.index.duplicated(keep="last")]

        # Resample 30m → 1h if needed
        if timeframe in ("1h", "60m"):
            df = self._resample_to_1h(df)

        # Apply corporate action adjustments (bonus/split) for equity symbols
        if self._adjust_prices and not instrument_key.startswith("NSE_INDEX"):
            if self._corp_actions is None:
                self._corp_actions = load_actions()
            df = apply_adjustments(df, symbol, self._corp_actions)

        df.to_parquet(cache_file)
        self._candle_cache.setdefault(symbol, {})[timeframe] = df
        logger.info(f"Fetched {len(df)} bars for {symbol}/{timeframe}")
        return df

    def _fetch_chunk(self, instrument_key: str, interval: str,
                      start: datetime, end: datetime) -> pd.DataFrame:
        from_str = start.strftime("%Y-%m-%d")
        to_str = end.strftime("%Y-%m-%d")
        key_encoded = instrument_key.replace("|", "%7C")
        endpoint = f"/historical-candle/{key_encoded}/{interval}/{to_str}/{from_str}"
        try:
            data = self._get(endpoint)
            candles = data.get("data", {}).get("candles", [])
            if not candles:
                return pd.DataFrame()
            # Upstox format: [datetime_str, open, high, low, close, volume, oi]
            df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df.set_index("ts", inplace=True)
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            return df
        except Exception as e:
            logger.error(f"Chunk fetch error {instrument_key} {from_str}→{to_str}: {e}")
            return pd.DataFrame()

    @staticmethod
    def _resample_to_1h(df: pd.DataFrame) -> pd.DataFrame:
        return df.resample("1h").agg({
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum",
        }).dropna()

    def get_cached(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        return self._candle_cache.get(symbol, {}).get(timeframe)

    # ── Intraday historical (today's data) ────────────────────────────────────

    def fetch_intraday(self, symbol: str, interval: str = "1minute") -> pd.DataFrame:
        """Fetch today's intraday candles (updated every 30 seconds on Upstox)."""
        instrument_key = self._resolve_key(symbol)
        if not instrument_key:
            return pd.DataFrame()
        key_encoded = instrument_key.replace("|", "%7C")
        endpoint = f"/historical-candle/intraday/{key_encoded}/{interval}"
        try:
            data = self._get(endpoint)
            candles = data.get("data", {}).get("candles", [])
            if not candles:
                return pd.DataFrame()
            df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            df.set_index("ts", inplace=True)
            return df[["open", "high", "low", "close", "volume"]].astype(float)
        except Exception as e:
            logger.error(f"Intraday fetch error {symbol}: {e}")
            return pd.DataFrame()

    # ── Market quotes ─────────────────────────────────────────────────────────

    def get_ltp(self, symbols: List[str]) -> Dict[str, float]:
        """Get Last Traded Price for multiple symbols."""
        keys = [self._resolve_key(s) for s in symbols if self._resolve_key(s)]
        if not keys:
            return {}
        try:
            data = self._get("/market-quote/ltp",
                              params={"symbol": ",".join(keys)})
            result = {}
            for key, info in data.get("data", {}).items():
                sym = self._key_to_symbol(key)
                result[sym] = float(info.get("last_price", 0))
            return result
        except Exception as e:
            logger.error(f"LTP fetch error: {e}")
            return {}

    def get_quotes(self, symbols: List[str]) -> Dict[str, dict]:
        """Get full OHLCV quote for multiple symbols."""
        keys = [self._resolve_key(s) for s in symbols if self._resolve_key(s)]
        if not keys:
            return {}
        try:
            data = self._get("/market-quote/quotes",
                              params={"symbol": ",".join(keys)})
            result = {}
            for key, info in data.get("data", {}).items():
                sym = self._key_to_symbol(key)
                ohlcv = info.get("ohlc", {})
                result[sym] = {
                    "ltp":    float(info.get("last_price", 0)),
                    "open":   float(ohlcv.get("open", 0)),
                    "high":   float(ohlcv.get("high", 0)),
                    "low":    float(ohlcv.get("low", 0)),
                    "close":  float(ohlcv.get("close", 0)),
                    "volume": int(info.get("volume", 0)),
                    "change_pct": float(info.get("net_change", 0)),
                }
            return result
        except Exception as e:
            logger.error(f"Quotes fetch error: {e}")
            return {}

    def get_market_depth(self, symbol: str) -> Optional[dict]:
        """Get full 5-level bid/ask depth."""
        key = self._resolve_key(symbol)
        if not key:
            return None
        try:
            data = self._get("/market-quote/depth",
                              params={"symbol": key, "mode": "full"})
            return data.get("data", {}).get(key)
        except Exception as e:
            logger.error(f"Depth fetch error {symbol}: {e}")
            return None

    # ── Option chain ──────────────────────────────────────────────────────────

    def get_option_chain(self, underlying: str, expiry_date: str) -> pd.DataFrame:
        """
        Fetch option chain for an underlying index/stock.

        Args:
            underlying: e.g. "NIFTY50" or instrument_key
            expiry_date: "YYYY-MM-DD"
        Returns:
            DataFrame with strike, call_ltp, put_ltp, call_oi, put_oi, etc.
        """
        key = self._resolve_key(underlying)
        if not key:
            return pd.DataFrame()
        try:
            data = self._get("/option/chain",
                              params={"instrument_key": key,
                                      "expiry_date": expiry_date})
            rows = []
            for item in data.get("data", []):
                call = item.get("call_options", {})
                put = item.get("put_options", {})
                md_call = call.get("market_data", {})
                md_put = put.get("market_data", {})
                rows.append({
                    "strike":     item.get("strike_price"),
                    "expiry":     expiry_date,
                    "call_ltp":   md_call.get("ltp", 0),
                    "call_oi":    md_call.get("oi", 0),
                    "call_iv":    md_call.get("iv", 0),
                    "call_volume": md_call.get("volume", 0),
                    "put_ltp":    md_put.get("ltp", 0),
                    "put_oi":     md_put.get("oi", 0),
                    "put_iv":     md_put.get("iv", 0),
                    "put_volume": md_put.get("volume", 0),
                })
            return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"Option chain error {underlying}: {e}")
            return pd.DataFrame()

    def get_expiry_dates(self, underlying: str) -> List[str]:
        """Get available expiry dates for F&O contracts."""
        key = self._resolve_key(underlying)
        if not key:
            return []
        try:
            data = self._get("/option/contract",
                              params={"instrument_key": key})
            return data.get("data", [])
        except Exception as e:
            logger.error(f"Expiry dates error {underlying}: {e}")
            return []

    # ── Polling-based streaming ────────────────────────────────────────────────

    def subscribe(self, callback: Callable) -> None:
        self._subscribers.append(callback)

    async def start_polling(self, symbols: List[str],
                             interval_sec: int = 60) -> None:
        """Poll LTP every interval_sec and emit candle events (fallback to WebSocket)."""
        self._running = True
        logger.info(f"Starting polling for {len(symbols)} symbols every {interval_sec}s")
        while self._running:
            quotes = self.get_quotes(symbols)
            for sym, q in quotes.items():
                event = {
                    "symbol": sym,
                    "timeframe": "poll",
                    "ts":     int(now_utc().timestamp() * 1000),
                    "open":   q["open"],
                    "high":   q["high"],
                    "low":    q["low"],
                    "close":  q["ltp"],
                    "volume": q["volume"],
                }
                for cb in self._subscribers:
                    await cb(event) if asyncio.iscoroutinefunction(cb) else cb(event)
            await asyncio.sleep(interval_sec)

    async def stop(self) -> None:
        self._running = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_key(self, symbol: str) -> Optional[str]:
        if "|" in symbol:
            return symbol  # already an instrument_key
        return self.registry.get_key(symbol)

    def _key_to_symbol(self, key: str) -> str:
        rec = self.registry.get_metadata(key)
        if rec:
            return rec.get("tradingsymbol", key)
        # fallback: strip exchange prefix
        return key.split("|")[-1] if "|" in key else key
