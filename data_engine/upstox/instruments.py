"""
Upstox Instrument Registry

Downloads and indexes the complete instrument master from Upstox.
Maps human-readable symbols (e.g. "RELIANCE", "NIFTY25MAYFUT") to
Upstox instrument keys (e.g. "NSE_EQ|INE002A01018").

Master CSV is cached locally and refreshed once per day.
"""
from __future__ import annotations
import csv
import gzip
import io
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("upstox.instruments")

# Upstox publishes fresh instrument files each morning before market open.
# One file per exchange holds every segment (equity, F&O, indices); records
# are filtered by their "exchange" column. (The older market-assets/.../v2/
# URLs return 403.)
_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{file}.csv.gz"
_INSTRUMENT_URLS = {
    "NSE_EQ":    _MASTER_URL.format(file="NSE"),
    "NSE_FO":    _MASTER_URL.format(file="NSE"),
    "NSE_INDEX": _MASTER_URL.format(file="NSE"),
    "BSE_EQ":    _MASTER_URL.format(file="BSE"),
    "BSE_FO":    _MASTER_URL.format(file="BSE"),
    "BSE_INDEX": _MASTER_URL.format(file="BSE"),
    "MCX_FO":    _MASTER_URL.format(file="MCX"),
}

# Fallback keys when the instrument master is unavailable: the project's
# universe and indices, from the single source of truth.
from config.instruments import INSTRUMENTS as KNOWN_INSTRUMENTS  # noqa: E402


class InstrumentRegistry:
    """
    Downloads, caches, and indexes Upstox instrument master files.
    Provides fast lookups: symbol → instrument_key, instrument_key → metadata.
    """

    def __init__(self, cache_dir: str = "data/instruments"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._by_symbol: Dict[str, dict] = {}   # tradingsymbol → record
        self._by_key: Dict[str, dict] = {}       # instrument_key → record
        self._loaded = False

    # ── Loading ────────────────────────────────────────────────────────────────

    def load(self, exchanges: List[str] | None = None,
              force_refresh: bool = False) -> None:
        exchanges = exchanges or ["NSE_EQ", "NSE_FO", "BSE_EQ", "NSE_INDEX"]
        for exch in exchanges:
            self._load_exchange(exch, force_refresh)
        # Seed with the project's verified universe (config/instruments.py —
        # checked against the master by tests/test_instrument_isins.py), so
        # the stocks we trade always resolve even when the master download
        # fails. Universe symbols always win: the master can hold an
        # unrelated instrument under the same ticker (e.g. "MIDCAP" is an
        # ETF there, but the universe's Nifty Midcap 150 index here).
        for sym, key in KNOWN_INSTRUMENTS.items():
            self._by_symbol[sym] = self._by_key.get(key) or {
                "instrument_key": key, "tradingsymbol": sym, "exchange": key.split("|")[0]}
        self._loaded = True
        logger.info(f"Instrument registry loaded: {len(self._by_symbol):,} symbols")

    def _load_exchange(self, exchange: str, force_refresh: bool) -> None:
        cache_file = self.cache_dir / f"{exchange}.json"
        # Use cached file if it's from today
        if cache_file.exists() and not force_refresh:
            age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
            if age_hours < 18:
                with open(cache_file) as f:
                    records = json.load(f)
                self._index_records(records)
                logger.info(f"Loaded {exchange} from cache: {len(records)} instruments")
                return

        url = _INSTRUMENT_URLS.get(exchange)
        if not url:
            return

        try:
            import requests
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            content = gzip.decompress(resp.content).decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            records = [r for r in reader if r.get("exchange", exchange) == exchange]
            with open(cache_file, "w") as f:
                json.dump(records, f)
            self._index_records(records)
            logger.info(f"Downloaded {exchange}: {len(records)} instruments")
        except Exception as e:
            logger.warning(f"Could not download {exchange} instruments: {e}")
            # Fall back to known instruments silently

    def _index_records(self, records: List[dict]) -> None:
        for rec in records:
            sym = rec.get("tradingsymbol", "").upper()
            key = rec.get("instrument_key", "")
            if sym:
                self._by_symbol[sym] = rec
            if key:
                self._by_key[key] = rec

    # ── Lookups ────────────────────────────────────────────────────────────────

    def get_key(self, symbol: str) -> Optional[str]:
        """Get instrument_key for a symbol. e.g. 'RELIANCE' → 'NSE_EQ|INE002A01018'"""
        rec = self._by_symbol.get(symbol.upper())
        if rec:
            return rec.get("instrument_key")
        # Fall back to the universe (config/instruments.py)
        return KNOWN_INSTRUMENTS.get(symbol.upper())

    def get_metadata(self, instrument_key: str) -> Optional[dict]:
        return self._by_key.get(instrument_key)

    def get_lot_size(self, instrument_key: str) -> int:
        rec = self._by_key.get(instrument_key, {})
        try:
            return int(rec.get("lot_size", 1))
        except (ValueError, TypeError):
            return 1

    def get_tick_size(self, instrument_key: str) -> float:
        rec = self._by_key.get(instrument_key, {})
        try:
            return float(rec.get("tick_size", 0.05))
        except (ValueError, TypeError):
            return 0.05

    def search(self, query: str, exchange: str = "NSE_EQ",
               limit: int = 10) -> List[dict]:
        """Fuzzy search for instruments matching query string."""
        q = query.upper()
        results = [
            rec for sym, rec in self._by_symbol.items()
            if q in sym and rec.get("exchange", "").startswith(exchange)
        ]
        return results[:limit]

    def nifty50_keys(self) -> List[str]:
        """Return instrument keys for all Nifty 50 constituent stocks."""
        nifty50_symbols = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
            "BAJFINANCE", "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK",
            "ASIANPAINT", "WIPRO", "MARUTI", "TITAN", "SUNPHARMA", "ULTRACEMCO",
            "NESTLEIND", "POWERGRID", "NTPC", "ONGC", "TECHM", "HCLTECH", "ITC",
            "ADANIPORTS", "BAJAJFINSV", "TATAMOTORS", "TATASTEEL", "JSWSTEEL",
        ]
        return [k for sym in nifty50_symbols if (k := self.get_key(sym))]

    def fo_instruments(self, underlying: str) -> List[dict]:
        """Return all F&O instruments for a given underlying symbol."""
        prefix = underlying.upper()
        return [rec for sym, rec in self._by_symbol.items()
                if sym.startswith(prefix) and rec.get("exchange") == "NSE_FO"]

    def round_to_tick(self, price: float, instrument_key: str) -> float:
        tick = self.get_tick_size(instrument_key)
        if tick <= 0:
            return price
        return round(round(price / tick) * tick, 10)
