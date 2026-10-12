"""
Indian market session utilities.
NSE/BSE trading hours: 09:15 – 15:30 IST, Mon–Fri, excluding holidays.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import List

import zoneinfo

logger = logging.getLogger(__name__)

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

MARKET_OPEN  = time(9, 15)
MARKET_CLOSE = time(15, 30)
PRE_OPEN     = time(9, 0)
AMO_START    = time(17, 0)

ROOT = Path(__file__).resolve().parent.parent.parent
_HOLIDAY_CACHE = ROOT / "data" / "nse_holidays.json"
_CACHE_TTL_DAYS = 30

# NSE 2025 holidays — fallback if API is unreachable
_NSE_HOLIDAYS_FALLBACK: List[date] = [
    date(2025, 1, 26),
    date(2025, 2, 26),
    date(2025, 3, 14),
    date(2025, 3, 31),
    date(2025, 4, 10),
    date(2025, 4, 14),
    date(2025, 4, 18),
    date(2025, 5, 1),
    date(2025, 8, 15),
    date(2025, 8, 27),
    date(2025, 10, 2),
    date(2025, 10, 20),
    date(2025, 10, 21),
    date(2025, 11, 5),
    date(2025, 12, 25),
]

_holiday_set: set[date] | None = None


def _fetch_nse_holidays() -> list[date]:
    url = "https://www.nseindia.com/api/holiday-master?type=trading"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        holidays: list[date] = []
        records = data if isinstance(data, list) else data.get("CM", data.get("data", []))
        for rec in records:
            raw = rec.get("tradingDate", rec.get("date", ""))
            for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
                try:
                    holidays.append(datetime.strptime(raw, fmt).date())
                    break
                except ValueError:
                    continue
        return holidays
    except Exception as exc:
        logger.debug("NSE holiday API unavailable: %s", exc)
        return []


def _load_holidays() -> set[date]:
    global _holiday_set
    if _holiday_set is not None:
        return _holiday_set

    cache_valid = False
    cached_dates: list[date] = []

    if _HOLIDAY_CACHE.exists():
        try:
            payload = json.loads(_HOLIDAY_CACHE.read_text())
            fetched_at = date.fromisoformat(payload["fetched_at"])
            if (date.today() - fetched_at).days < _CACHE_TTL_DAYS:
                cached_dates = [date.fromisoformat(d) for d in payload["holidays"]]
                cache_valid = True
        except Exception:
            pass

    if not cache_valid:
        fetched = _fetch_nse_holidays()
        if fetched:
            cached_dates = fetched
            try:
                _HOLIDAY_CACHE.parent.mkdir(parents=True, exist_ok=True)
                _HOLIDAY_CACHE.write_text(json.dumps({
                    "fetched_at": date.today().isoformat(),
                    "holidays": [d.isoformat() for d in fetched],
                }))
            except Exception as exc:
                logger.debug("Could not write holiday cache: %s", exc)
        else:
            # API unreachable — fall back to the static list plus any dates in
            # config/settings.yaml india_market.holidays (keep that list
            # current each year; it is the only offline source after 2025).
            cached_dates = _NSE_HOLIDAYS_FALLBACK + _configured_holidays()

    _holiday_set = set(cached_dates)
    return _holiday_set


def _configured_holidays() -> list[date]:
    try:
        from config.loader import Settings
        raw = Settings().get("india_market.holidays") or []
        return [date.fromisoformat(str(d)) for d in raw]
    except Exception as exc:
        logger.debug("Could not read india_market.holidays: %s", exc)
        return []


def is_holiday(d: date | None = None) -> bool:
    d = d or date.today()
    return d in _load_holidays()


def now_ist() -> datetime:
    return datetime.now(IST)


def is_market_open(dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    if dt.weekday() >= 5:
        return False
    if is_holiday(dt.date()):
        return False
    t = dt.time()
    return MARKET_OPEN <= t <= MARKET_CLOSE


def is_pre_open(dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    t = dt.astimezone(IST).time()
    return PRE_OPEN <= t < MARKET_OPEN


def is_amo_window(dt: datetime | None = None) -> bool:
    dt = dt or now_ist()
    t = dt.astimezone(IST).time()
    return t >= AMO_START or t < PRE_OPEN


def minutes_to_close(dt: datetime | None = None) -> int:
    dt = dt or now_ist()
    if not is_market_open(dt):
        return 0
    close_dt = dt.replace(hour=15, minute=30, second=0, microsecond=0)
    delta = close_dt - dt
    return max(0, int(delta.total_seconds() / 60))


def next_market_open() -> datetime:
    dt = now_ist()
    for _ in range(14):
        dt = dt.replace(hour=9, minute=15, second=0, microsecond=0)
        if dt < now_ist():
            dt += timedelta(days=1)
        if dt.weekday() < 5 and not is_holiday(dt.date()):
            return dt
        dt += timedelta(days=1)
    return dt
