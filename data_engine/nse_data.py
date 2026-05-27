"""
NSE public data scraper — FII/DII activity, delivery volumes,
F&O ban list, corporate actions, and securities in ban period.

All data is publicly available on nseindia.com and is free to use.
Sources:
  - FII/DII: https://www.nseindia.com/api/fiidiiTradeReact
  - F&O Ban:  https://www.nseindia.com/api/fo-secban
  - Delivery: https://archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
  - Corp actions: https://www.nseindia.com/api/corporates-corporateActions
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from utils.logger import get_logger

logger = get_logger("nse_data")

_CACHE_DIR = Path("data/nse_cache")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(_NSE_HEADERS)
        # Hit homepage first to get cookies (NSE requires this)
        try:
            _SESSION.get("https://www.nseindia.com", timeout=10)
            time.sleep(0.5)
        except Exception:
            pass
    return _SESSION


def _nse_get(url: str, timeout: int = 15) -> Optional[dict]:
    """GET from NSE with session cookies."""
    try:
        resp = _get_session().get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"NSE GET failed {url}: {e}")
        return None


# ── FII / DII Data ────────────────────────────────────────────────────────────

def fetch_fii_dii_activity(days: int = 30) -> pd.DataFrame:
    """
    Fetch FII/DII net buy/sell data for the past N days.

    Returns DataFrame with columns:
        date, fii_net_cash, dii_net_cash, fii_net_fo, combined_net
    """
    cache_path = _CACHE_DIR / f"fii_dii_{date.today()}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    url = "https://www.nseindia.com/api/fiidiiTradeReact"
    data = _nse_get(url)
    if not data:
        return _load_fii_fallback()

    rows = []
    for item in data:
        try:
            rows.append({
                "date": pd.to_datetime(item.get("date", ""), dayfirst=True),
                "fii_net_cash": _parse_cr(item.get("fiiNet", 0)),
                "dii_net_cash": _parse_cr(item.get("diiNet", 0)),
            })
        except Exception:
            continue

    if not rows:
        return _load_fii_fallback()

    df = pd.DataFrame(rows).dropna(subset=["date"])
    df["combined_net"] = df["fii_net_cash"] + df["dii_net_cash"]
    df = df.sort_values("date").tail(days).reset_index(drop=True)

    try:
        df.to_parquet(cache_path)
    except Exception:
        pass

    return df


def get_fii_sentiment(lookback_days: int = 5) -> dict:
    """
    Returns FII/DII sentiment signal for directional bias.

    Signal:
    - fii_5d_net > threshold → BULLISH (FII net buyer)
    - fii_5d_net < -threshold → BEARISH (FII net seller)
    - |fii_5d_net| < threshold → NEUTRAL
    """
    df = fetch_fii_dii_activity(lookback_days + 5)
    if df.empty:
        return {"signal": "NEUTRAL", "fii_net": 0.0, "dii_net": 0.0, "combined_net": 0.0}

    recent = df.tail(lookback_days)
    fii_net   = float(recent["fii_net_cash"].sum())
    dii_net   = float(recent["dii_net_cash"].sum())
    combined  = float(recent["combined_net"].sum())

    threshold = 1000.0  # ₹1000 Cr net as meaningful signal
    if fii_net > threshold:
        signal = "BULLISH"
    elif fii_net < -threshold:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    return {
        "signal": signal,
        "fii_net": round(fii_net, 2),
        "dii_net": round(dii_net, 2),
        "combined_net": round(combined, 2),
        "days": lookback_days,
        "fii_daily_avg": round(fii_net / lookback_days, 2),
    }


def _load_fii_fallback() -> pd.DataFrame:
    """Return last cached data if available."""
    files = sorted(_CACHE_DIR.glob("fii_dii_*.parquet"))
    if files:
        return pd.read_parquet(files[-1])
    return pd.DataFrame(columns=["date", "fii_net_cash", "dii_net_cash", "combined_net"])


def _parse_cr(val) -> float:
    """Parse crore value, handling commas and strings."""
    try:
        return float(str(val).replace(",", "").replace("(", "-").replace(")", ""))
    except Exception:
        return 0.0


# ── F&O Ban List ──────────────────────────────────────────────────────────────

def fetch_fo_ban_list() -> List[str]:
    """
    Fetch today's F&O securities ban list from NSE.
    Returns list of symbols in ban period.
    Cached for the current trading day.
    """
    cache_path = _CACHE_DIR / f"fo_ban_{date.today()}.json"
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    url = "https://www.nseindia.com/api/fo-secban"
    data = _nse_get(url)
    if not data:
        return _load_ban_fallback()

    banned = []
    try:
        # NSE returns {"data": [{"symbol": "..."}, ...]}
        items = data.get("data", data if isinstance(data, list) else [])
        for item in items:
            sym = item.get("symbol", "").strip().upper()
            if sym:
                banned.append(sym)
    except Exception as e:
        logger.warning(f"Ban list parse error: {e}")
        return _load_ban_fallback()

    with open(cache_path, "w") as f:
        json.dump(banned, f)

    if banned:
        logger.info(f"F&O ban list: {len(banned)} symbols — {', '.join(banned[:10])}")
    else:
        logger.info("F&O ban list: no symbols banned today")

    return banned


def is_in_fo_ban(symbol: str) -> bool:
    """Returns True if symbol is in today's F&O ban list."""
    banned = fetch_fo_ban_list()
    return symbol.upper() in banned


def _load_ban_fallback() -> List[str]:
    files = sorted(_CACHE_DIR.glob("fo_ban_*.json"))
    if files:
        with open(files[-1]) as f:
            return json.load(f)
    return []


# ── Delivery Volume ───────────────────────────────────────────────────────────

def fetch_delivery_data(trade_date: Optional[date] = None) -> pd.DataFrame:
    """
    Fetch NSE bhav copy with delivery percentage for all stocks.
    Delivery% = genuine buy/sell (not intraday noise).
    High delivery (>50%) = genuine accumulation signal.

    Returns DataFrame: symbol, close, volume, delivery_qty, delivery_pct
    """
    if trade_date is None:
        trade_date = _last_trading_day()

    cache_path = _CACHE_DIR / f"delivery_{trade_date.strftime('%Y%m%d')}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    date_str = trade_date.strftime("%d%m%Y")
    url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"

    try:
        resp = _get_session().get(url, timeout=20)
        resp.raise_for_status()
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))

        # Column names vary — normalise
        df.columns = [c.strip().upper().replace(" ", "_") for c in df.columns]
        col_map = {
            "SYMBOL": "symbol", "CLOSE_PRICE": "close", "TTL_TRD_QNTY": "volume",
            "DELIV_QTY": "delivery_qty", "DELIV_PER": "delivery_pct",
        }
        rename = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=rename)

        keep = [c for c in ["symbol", "close", "volume", "delivery_qty", "delivery_pct"] if c in df.columns]
        df = df[keep].dropna(subset=["symbol"])
        df["symbol"] = df["symbol"].str.strip().str.upper()

        df.to_parquet(cache_path)
        return df

    except Exception as e:
        logger.warning(f"Delivery data fetch failed for {trade_date}: {e}")
        return pd.DataFrame(columns=["symbol", "close", "volume", "delivery_qty", "delivery_pct"])


def get_delivery_pct(symbol: str, trade_date: Optional[date] = None) -> Optional[float]:
    """Returns delivery percentage for a symbol on given date."""
    df = fetch_delivery_data(trade_date)
    if df.empty:
        return None
    row = df[df["symbol"] == symbol.upper()]
    if row.empty:
        return None
    return float(row["delivery_pct"].iloc[0])


def get_high_delivery_stocks(
    min_delivery_pct: float = 50.0,
    trade_date: Optional[date] = None,
) -> pd.DataFrame:
    """Returns stocks with delivery% >= threshold (genuine accumulation)."""
    df = fetch_delivery_data(trade_date)
    if df.empty or "delivery_pct" not in df.columns:
        return df
    return df[df["delivery_pct"] >= min_delivery_pct].sort_values("delivery_pct", ascending=False)


# ── Corporate Actions ──────────────────────────────────────────────────────────

def fetch_corporate_actions(days_ahead: int = 30) -> pd.DataFrame:
    """
    Fetch upcoming corporate actions: dividends, splits, bonuses, rights.
    Useful to avoid holding through ex-dates.
    """
    cache_path = _CACHE_DIR / f"corp_actions_{date.today()}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    url = (
        "https://www.nseindia.com/api/corporates-corporateActions"
        "?index=equities&from_date=&to_date=&csv=true"
    )
    data = _nse_get(url)
    if not data:
        return pd.DataFrame()

    rows = []
    try:
        items = data if isinstance(data, list) else data.get("data", [])
        for item in items:
            rows.append({
                "symbol":   item.get("symbol", "").strip().upper(),
                "action":   item.get("subject", "").strip(),
                "ex_date":  pd.to_datetime(item.get("exDate", ""), dayfirst=True, errors="coerce"),
                "purpose":  item.get("purpose", "").strip(),
            })
    except Exception as e:
        logger.warning(f"Corporate actions parse error: {e}")

    df = pd.DataFrame(rows).dropna(subset=["ex_date"])
    cutoff = pd.Timestamp(date.today() + timedelta(days=days_ahead))
    df = df[df["ex_date"] <= cutoff].sort_values("ex_date")

    try:
        df.to_parquet(cache_path)
    except Exception:
        pass

    return df


def has_upcoming_corporate_action(symbol: str, days: int = 5) -> Optional[dict]:
    """Returns action dict if symbol has a corporate action within N days, else None."""
    df = fetch_corporate_actions(days)
    if df.empty:
        return None
    today = pd.Timestamp(date.today())
    upcoming = df[
        (df["symbol"] == symbol.upper()) &
        (df["ex_date"] >= today) &
        (df["ex_date"] <= today + pd.Timedelta(days=days))
    ]
    if upcoming.empty:
        return None
    row = upcoming.iloc[0]
    return {
        "symbol":  row["symbol"],
        "action":  row["action"],
        "ex_date": str(row["ex_date"].date()),
        "purpose": row["purpose"],
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _last_trading_day() -> date:
    """Return the most recent NSE trading weekday."""
    today = date.today()
    delta = 1
    candidate = today - timedelta(days=delta)
    while candidate.weekday() >= 5:  # 5=Sat, 6=Sun
        delta += 1
        candidate = today - timedelta(days=delta)
    return candidate
