"""
India VIX data engine.

India VIX (Volatility Index) measures the market's expectation of near-term
volatility and is computed from Nifty options prices.

It is the SINGLE MOST PREDICTIVE macro indicator for Nifty direction:
- VIX rising + Nifty falling → panic selling, near-term bottom likely
- VIX falling + Nifty rising → complacency, stable uptrend
- VIX spike > 20% in a day → extreme fear → mean-reversion buy opportunity
- VIX < 12 for extended period → market overconfidence → good time to buy puts

Sources:
- Upstox historical: NSE_INDEX|India VIX
- NSE website (backup): https://archives.nseindia.com/content/indices/ind_VIX_history.csv
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

from config.instruments import INDEX_INSTRUMENTS
from utils.logger import get_logger

logger = get_logger("india_vix")

_CACHE_DIR = Path("data/nse_cache")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

VIX_INSTRUMENT_KEY = INDEX_INSTRUMENTS["VIXINDIA"]

# Thresholds based on empirical NSE data
VIX_EXTREME_FEAR   = 25.0   # panic territory → potential reversal up
VIX_HIGH           = 20.0   # elevated risk
VIX_NORMAL_HIGH    = 15.0   # normal-elevated
VIX_NORMAL_LOW     = 12.0   # normal-low
VIX_COMPLACENCY    = 10.0   # extreme complacency → tail risk builds up


def fetch_vix_history_nse(lookback_days: int = 365) -> pd.DataFrame:
    """
    Fetch India VIX historical data from NSE archives.
    Returns DataFrame with columns: date, open, high, low, close, prev_close, change_pct
    """
    cache_path = _CACHE_DIR / f"india_vix_{date.today()}.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if len(df) >= lookback_days:
            return df.tail(lookback_days)

    url = "https://archives.nseindia.com/content/indices/ind_VIX_history.csv"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Referer": "https://www.nseindia.com/",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        df.columns = [c.strip() for c in df.columns]

        col_map = {
            "Date": "date", "Open": "open", "High": "high",
            "Low": "low", "Close": "close",
            "Previous Close": "prev_close", "Change(%)": "change_pct",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

        df.to_parquet(cache_path)
        logger.info(f"India VIX: loaded {len(df)} records from NSE")
        return df.tail(lookback_days)

    except Exception as e:
        logger.warning(f"India VIX NSE fetch failed: {e}")
        return _load_vix_fallback(lookback_days)


def get_current_vix(upstox_data_engine=None) -> Optional[float]:
    """
    Get current India VIX from Upstox LTP or fall back to last known close.
    """
    if upstox_data_engine is not None:
        try:
            ltp_map = upstox_data_engine.get_ltp([VIX_INSTRUMENT_KEY])
            vix = ltp_map.get(VIX_INSTRUMENT_KEY)
            if vix and vix > 0:
                return float(vix)
        except Exception as e:
            logger.debug(f"VIX from Upstox failed: {e}")

    # Fallback to last historical close
    df = fetch_vix_history_nse(5)
    if not df.empty and "close" in df.columns:
        return float(df["close"].iloc[-1])
    return None


def classify_vix(vix: float) -> str:
    """Classify VIX level into a regime string."""
    if vix >= VIX_EXTREME_FEAR:
        return "EXTREME_FEAR"
    if vix >= VIX_HIGH:
        return "HIGH_FEAR"
    if vix >= VIX_NORMAL_HIGH:
        return "ELEVATED"
    if vix >= VIX_NORMAL_LOW:
        return "NORMAL"
    if vix >= VIX_COMPLACENCY:
        return "LOW"
    return "EXTREME_COMPLACENCY"


def vix_percentile(current_vix: float, lookback_days: int = 252) -> float:
    """How elevated is current VIX vs past year? [0, 100]"""
    df = fetch_vix_history_nse(lookback_days)
    if df.empty or "close" not in df.columns:
        return 50.0
    hist = df["close"].dropna().values
    return float(np.mean(hist < current_vix) * 100.0)


def vix_spike_today(threshold_pct: float = 15.0, upstox_data_engine=None) -> bool:
    """Returns True if VIX has spiked > threshold% intraday vs yesterday's close."""
    df = fetch_vix_history_nse(3)
    if df.empty or "close" not in df.columns:
        return False
    prev_close = float(df["close"].iloc[-1])
    current = get_current_vix(upstox_data_engine)
    if current is None:
        return False
    change_pct = (current - prev_close) / prev_close * 100.0
    return change_pct >= threshold_pct


def _load_vix_fallback(lookback_days: int) -> pd.DataFrame:
    files = sorted(_CACHE_DIR.glob("india_vix_*.parquet"))
    if files:
        df = pd.read_parquet(files[-1])
        return df.tail(lookback_days)
    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "change_pct"])
