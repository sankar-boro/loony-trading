"""
Corporate action adjustment for NSE equities.

Upstox historical-candle API returns unadjusted prices.
A 1:1 bonus halves the price overnight — without adjustment this looks
like a 50% crash to every strategy.

Data source: NSE corporate actions API (public, no auth required).
Cache: data/corporate_actions.json — refreshed at most once per day.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from utils.logger import get_logger

logger = get_logger("corporate_actions")

_CACHE_FILE = Path(__file__).resolve().parents[2] / "data" / "corporate_actions.json"
_CACHE_TTL_HOURS = 24
_NSE_URL = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=equities&from_date={from_d}&to_date={to_d}"
)
_NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


def _fetch_nse_actions(lookback_years: int = 3) -> list[dict]:
    """Download corporate actions from NSE. Returns raw list of action dicts."""
    import requests

    today = date.today()
    from_d = (today - timedelta(days=lookback_years * 365)).strftime("%d-%m-%Y")
    to_d   = today.strftime("%d-%m-%Y")
    url = _NSE_URL.format(from_d=from_d, to_d=to_d)

    session = requests.Session()
    # NSE requires a cookie — first hit the homepage
    try:
        session.get("https://www.nseindia.com/", headers=_NSE_HEADERS, timeout=10)
    except Exception:
        pass

    try:
        r = session.get(url, headers=_NSE_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"NSE corporate actions fetch failed: {e}")
        return []


def _parse_actions(raw: list[dict]) -> dict[str, list[dict]]:
    """
    Parse raw NSE records into a dict keyed by symbol.
    Each value is a list of adjustment events sorted by ex_date ascending.

    Supported action types and their adjustment factors:
      • Bonus  "1:1" → factor 0.5 (price halves for pre-bonus bars)
      • Bonus  "2:1" → factor 0.333... (new share per 2 held)
      • Split  "1:10"→ factor 0.1  (10 → 1 share)
    """
    result: dict[str, list[dict]] = {}

    for item in raw:
        symbol = (item.get("symbol") or "").strip().upper()
        action_type = (item.get("subject") or item.get("action") or "").upper()
        ex_date_str = (item.get("exDate") or item.get("ex_date") or "").strip()

        if not symbol or not ex_date_str:
            continue

        factor: Optional[float] = None

        if "BONUS" in action_type:
            # e.g. "BONUS 1:1", "BONUS SHARES 2:1"
            factor = _parse_ratio_factor(action_type, invert=True)
        elif "SPLIT" in action_type or "SUBDIVISION" in action_type:
            # e.g. "STOCK SPLIT 1:10" means 1 new share per 10 old → price ÷ 10
            factor = _parse_ratio_factor(action_type, invert=True)
        elif "RIGHTS" in action_type:
            # Rights issue dilution — approximate as small downward adjustment
            factor = _parse_ratio_factor(action_type, invert=True)

        if factor is None or factor <= 0 or factor >= 1.0:
            continue   # only process price-reducing events

        try:
            # NSE dates can be DD-Mon-YYYY or YYYY-MM-DD
            ex_date = _parse_date(ex_date_str)
        except Exception:
            continue

        result.setdefault(symbol, []).append({
            "ex_date": ex_date.isoformat(),
            "factor": factor,
            "action": action_type[:60],
        })

    # Sort each symbol's list ascending by ex_date
    for sym in result:
        result[sym].sort(key=lambda x: x["ex_date"])

    return result


def _parse_ratio_factor(text: str, invert: bool = True) -> Optional[float]:
    """
    Extract adjustment factor from strings like "BONUS 1:1", "SPLIT 1:10".
    For bonus "1:1": new shares = existing, so total doubles → price halves → factor 0.5.
    For split "1:10": 10 shares → 1 new → factor 0.1.
    `invert=True` treats A:B as B/(A+B) for bonus, B/A for splits — caller picks.
    """
    import re
    m = re.search(r"(\d+)\s*:\s*(\d+)", text)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a <= 0 or b <= 0:
        return None
    # For bonus "new:existing" — total shares = a+b, factor = b/(a+b) (pre-bonus held)
    # We use b/(a+b) for bonus, b/a for splits (both result in price reduction)
    if "BONUS" in text.upper():
        return b / (a + b)
    else:
        # Split/subdivision: factor = 1 / (new shares per old)
        return min(a, b) / max(a, b)


def _parse_date(s: str) -> date:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {s!r}")


def load_actions(force_refresh: bool = False) -> dict[str, list[dict]]:
    """
    Load corporate actions from cache, refreshing if stale.
    Returns {SYMBOL: [{ex_date, factor, action}, ...]} sorted by ex_date.
    """
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not force_refresh and _CACHE_FILE.exists():
        age_h = (time.time() - _CACHE_FILE.stat().st_mtime) / 3600
        if age_h < _CACHE_TTL_HOURS:
            try:
                return json.loads(_CACHE_FILE.read_text())
            except Exception:
                pass

    logger.info("Refreshing NSE corporate actions cache...")
    raw = _fetch_nse_actions()
    if not raw:
        # Return stale cache rather than empty data
        if _CACHE_FILE.exists():
            try:
                logger.warning("Using stale corporate actions cache")
                return json.loads(_CACHE_FILE.read_text())
            except Exception:
                pass
        return {}

    parsed = _parse_actions(raw)
    try:
        _CACHE_FILE.write_text(json.dumps(parsed, indent=2))
        logger.info(
            f"Corporate actions cached: {len(parsed)} symbols, "
            f"{sum(len(v) for v in parsed.values())} events"
        )
    except Exception as e:
        logger.warning(f"Could not write corporate actions cache: {e}")

    return parsed


def apply_adjustments(df: pd.DataFrame, symbol: str,
                      actions: dict[str, list[dict]]) -> pd.DataFrame:
    """
    Backward-adjust OHLC prices for corporate actions.

    For each action event on ex_date, multiply all OHLC prices BEFORE
    that date by `factor` so the historical series is continuous.

    Volume is left unadjusted (adjusted volume would be misleading for
    liquidity analysis).
    """
    sym_actions = actions.get(symbol.upper(), [])
    if not sym_actions:
        return df

    df = df.copy()
    price_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]

    for event in reversed(sym_actions):   # apply most recent first
        ex_date = pd.Timestamp(event["ex_date"])
        if df.index.tz is not None and ex_date.tzinfo is None:
            ex_date = ex_date.tz_localize(df.index.tz)
        factor  = float(event["factor"])
        mask    = df.index < ex_date
        if not mask.any():
            continue
        for col in price_cols:
            df.loc[mask, col] = df.loc[mask, col] * factor
        logger.debug(
            f"{symbol}: applied adjustment factor {factor:.4f} "
            f"before {ex_date.date()} ({event['action'][:40]})"
        )

    return df
