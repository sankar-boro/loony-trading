"""
Indian market session utilities.
NSE/BSE trading hours: 09:15 – 15:30 IST, Mon–Fri, excluding holidays.
"""
from __future__ import annotations
from datetime import datetime, time, date
from typing import List
import zoneinfo

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

MARKET_OPEN  = time(9, 15)
MARKET_CLOSE = time(15, 30)
PRE_OPEN     = time(9, 0)
AMO_START    = time(17, 0)   # after-market order window opens

# NSE 2024-2025 holidays (extend as needed)
_NSE_HOLIDAYS_2025: List[date] = [
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramadan Eid)
    date(2025, 4, 10),   # Shri Ram Navami
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti
    date(2025, 10, 2),   # Dussehra
    date(2025, 10, 20),  # Diwali - Laxmi Pujan
    date(2025, 10, 21),  # Diwali - Balipratipada
    date(2025, 11, 5),   # Prakash Gurpurb Sri Guru Nanak Dev
    date(2025, 12, 25),  # Christmas
]


def now_ist() -> datetime:
    return datetime.now(IST)


def is_market_open(dt: datetime | None = None) -> bool:
    """Returns True if NSE/BSE is currently in normal trading session."""
    dt = dt or now_ist()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    if dt.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    if dt.date() in _NSE_HOLIDAYS_2025:
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
    """Minutes remaining until market close; 0 if market is closed."""
    dt = dt or now_ist()
    if not is_market_open(dt):
        return 0
    close_dt = dt.replace(hour=15, minute=30, second=0, microsecond=0)
    delta = close_dt - dt
    return max(0, int(delta.total_seconds() / 60))


def next_market_open() -> datetime:
    """Return the next NSE market open datetime in IST."""
    dt = now_ist()
    for _ in range(10):
        dt = dt.replace(hour=9, minute=15, second=0, microsecond=0)
        if dt < now_ist():
            from datetime import timedelta
            dt += timedelta(days=1)
        if dt.weekday() < 5 and dt.date() not in _NSE_HOLIDAYS_2025:
            return dt
        from datetime import timedelta
        dt += timedelta(days=1)
    return dt
