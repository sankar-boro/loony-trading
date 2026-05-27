from datetime import datetime, timezone, time as dt_time, timedelta
import zoneinfo

IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# MIS auto-squareoff: Upstox squares off all intraday positions at 3:20 PM IST.
# We close at 3:14 PM to get a controlled fill before the broker does it.
_MIS_SQUAREOFF_TIME = dt_time(15, 14)
_MARKET_CLOSE_TIME  = dt_time(15, 30)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    return datetime.now(IST)


def to_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def from_timestamp(ts: int | float) -> datetime:
    if ts > 1e12:
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def should_squareoff_mis() -> bool:
    """
    Returns True once the clock passes 3:14 PM IST.
    Call this on every price tick; the caller is responsible for
    ensuring the squareoff fires exactly once per session using a flag.
    """
    return now_ist().time() >= _MIS_SQUAREOFF_TIME


def minutes_to_squareoff() -> int:
    """Minutes until the MIS squareoff window (3:14 PM IST). 0 if already past."""
    ist = now_ist()
    target = ist.replace(hour=15, minute=14, second=0, microsecond=0)
    delta = (target - ist).total_seconds()
    return max(0, int(delta / 60))


def is_market_session() -> bool:
    """True between 9:15 AM and 3:30 PM IST on weekdays (ignores holidays)."""
    ist = now_ist()
    if ist.weekday() >= 5:
        return False
    t = ist.time()
    return dt_time(9, 15) <= t <= _MARKET_CLOSE_TIME


def next_market_open() -> datetime:
    """Returns the next 9:15 AM IST open as an IST-aware datetime (skips weekends)."""
    ist = now_ist()
    candidate = ist.replace(hour=9, minute=15, second=0, microsecond=0)
    if ist >= candidate:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def minutes_to_market_open() -> int:
    """Minutes until the next market open. 0 if market is already open."""
    if is_market_session():
        return 0
    delta = (next_market_open() - now_ist()).total_seconds()
    return max(0, int(delta / 60))


def minutes_to_market_close() -> int:
    """Minutes until market close (3:30 PM IST). 0 if already closed."""
    ist = now_ist()
    target = ist.replace(hour=15, minute=30, second=0, microsecond=0)
    delta = (target - ist).total_seconds()
    return max(0, int(delta / 60))
