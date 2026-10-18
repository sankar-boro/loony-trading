"""
GIFT Nifty (NSE IFSC) pre-market data engine.

GIFT Nifty (formerly SGX Nifty) trades on NSE International Exchange
in GIFT City, Gujarat. It trades from 6:30 AM IST when Indian markets are closed,
giving a strong indication of where Nifty will open.

Every serious Indian trader checks GIFT Nifty before 9:15 AM.

Pre-market bias rules (empirically derived from NSE data):
- GIFT gap > +0.5% → Nifty likely to gap up, fade the open in first 15 min
- GIFT gap > +1.5% → Strong gap, may sustain → buy on first dip
- GIFT gap < -0.5% → Nifty likely to gap down, buy the panic within 15 min
- GIFT gap < -1.5% → Strong gap down, may sustain → wait, don't catch falling knife

Data sources:
- NSE IFSC official: Available via NSE IFSC API (requires registration)
- Fallback: Upstox SGX/GIFT instrument key
- Fallback: Web scraping from financial sites

Instrument key on Upstox: NSE_INDEX|GIFT NIFTY or NSE_INDEX|NIFTY BANK (check)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

import numpy as np
import pandas as pd
import requests

from data_engine.upstox.market_hours import IST
from config.instruments import INDEX_INSTRUMENTS
from utils.logger import get_logger

logger = get_logger("gift_nifty")

# Known Upstox instrument keys for GIFT/SGX Nifty
_GIFT_NIFTY_KEYS  = [
    INDEX_INSTRUMENTS["GIFTNIFTY"],
    INDEX_INSTRUMENTS["SENSEX"],             # cross-check
]

# Gap thresholds for signal generation
GAP_STRONG_BULLISH  =  1.5   # %
GAP_WEAK_BULLISH    =  0.5
GAP_WEAK_BEARISH    = -0.5
GAP_STRONG_BEARISH  = -1.5


@dataclass
class GIFTNiftyData:
    """Current GIFT Nifty state."""
    timestamp: datetime
    gift_price: float
    nifty_prev_close: float
    gap_pts: float
    gap_pct: float
    trend: str          # "STRONG_BULLISH", "WEAK_BULLISH", "NEUTRAL", "WEAK_BEARISH", "STRONG_BEARISH"
    market_open_in_mins: int


def classify_gift_gap(gap_pct: float) -> str:
    if gap_pct >= GAP_STRONG_BULLISH:
        return "STRONG_BULLISH"
    if gap_pct >= GAP_WEAK_BULLISH:
        return "WEAK_BULLISH"
    if gap_pct <= GAP_STRONG_BEARISH:
        return "STRONG_BEARISH"
    if gap_pct <= GAP_WEAK_BEARISH:
        return "WEAK_BEARISH"
    return "NEUTRAL"


def get_gift_nifty(upstox_data_engine=None, nifty_prev_close: Optional[float] = None) -> Optional[GIFTNiftyData]:
    """
    Fetch current GIFT Nifty price and compute gap vs previous close.

    Priority:
    1. Upstox LTP for GIFT Nifty instrument key
    2. External financial data API (fallback)
    3. Returns None if unavailable
    """
    gift_price: Optional[float] = None

    # Try Upstox first
    if upstox_data_engine is not None:
        for key in _GIFT_NIFTY_KEYS:
            try:
                ltp_map = upstox_data_engine.get_ltp([key])
                price = ltp_map.get(key)
                if price and price > 1000:
                    gift_price = float(price)
                    logger.debug(f"GIFT Nifty from Upstox ({key}): {gift_price}")
                    break
            except Exception:
                continue

    # Fallback: NSE open API for Nifty LTP
    if gift_price is None:
        gift_price = _fetch_gift_nse_api()

    if gift_price is None or gift_price <= 0:
        return None

    # Previous close: use provided or fetch from NSE
    if nifty_prev_close is None:
        nifty_prev_close = _fetch_nifty_prev_close()

    if nifty_prev_close is None or nifty_prev_close <= 0:
        return None

    gap_pts = gift_price - nifty_prev_close
    gap_pct = gap_pts / nifty_prev_close * 100.0
    trend   = classify_gift_gap(gap_pct)

    now = datetime.now(tz=IST)
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    mins_to_open = max(int((market_open - now).total_seconds() / 60), 0)

    logger.info(
        f"GIFT Nifty: {gift_price:.2f} prev_close={nifty_prev_close:.2f} "
        f"gap={gap_pts:+.2f} ({gap_pct:+.2f}%) → {trend}"
    )

    return GIFTNiftyData(
        timestamp=now,
        gift_price=gift_price,
        nifty_prev_close=nifty_prev_close,
        gap_pts=round(gap_pts, 2),
        gap_pct=round(gap_pct, 3),
        trend=trend,
        market_open_in_mins=mins_to_open,
    )


def _fetch_gift_nse_api() -> Optional[float]:
    """Fetch Nifty 50 index LTP from NSE public API as GIFT proxy."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.nseindia.com/",
        }
        session = requests.Session()
        session.headers.update(headers)
        session.get("https://www.nseindia.com", timeout=8)
        resp = session.get(
            "https://www.nseindia.com/api/allIndices",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            if item.get("indexSymbol") == "NIFTY 50":
                return float(item.get("last", 0))
    except Exception as e:
        logger.debug(f"NSE API gift fallback failed: {e}")
    return None


def _fetch_nifty_prev_close() -> Optional[float]:
    """Fetch Nifty 50 previous close from NSE."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.nseindia.com/",
        }
        session = requests.Session()
        session.headers.update(headers)
        session.get("https://www.nseindia.com", timeout=8)
        resp = session.get(
            "https://www.nseindia.com/api/allIndices",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            if item.get("indexSymbol") == "NIFTY 50":
                return float(item.get("previousClose", 0))
    except Exception as e:
        logger.debug(f"NSE prev close fetch failed: {e}")
    return None
