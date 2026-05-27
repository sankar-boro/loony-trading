from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def from_timestamp(ts: int | float) -> datetime:
    if ts > 1e12:
        ts = ts / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc)
