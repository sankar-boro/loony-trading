"""
Historical analogue engine (MarketPulse AI Phase 3).

Retrieves matured HistoricalEvent rows sharing an event's event_type
(optionally narrowed by direction/regime) and reports win-rate + median
return at each forward horizon. This is retrieval and aggregation of
*realized* past outcomes — explicitly not a prediction (spec §22): callers
must label it "historical analysis" in any UI, never "forecast".

15m/1h horizons are frequently unavailable — this project's price data is
daily bars (Upstox V2 doesn't support a working 15-minute interval; see
Phase 1 gap notes), so most HistoricalEvent rows only have 1d/5d realized
outcomes. Horizons with zero samples are reported honestly as such rather
than silently omitted, so a caller can tell "no edge" from "no data".
"""
from __future__ import annotations
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from db.models import HistoricalEvent

_HORIZON_FIELDS = {
    "15m": "price_after_15m", "1h": "price_after_1h",
    "1d": "price_after_1d", "5d": "price_after_5d",
}


@dataclass
class HorizonStats:
    horizon: str
    sample_count: int
    win_rate_pct: float | None
    median_return_pct: float | None


@dataclass
class AnalogueResult:
    event_type: str
    direction: str | None
    total_samples: int
    horizons: list[HorizonStats] = field(default_factory=list)


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _returns_for_horizon(events: list[HistoricalEvent], field_name: str) -> list[float]:
    out = []
    for e in events:
        after = getattr(e, field_name)
        if e.price_before and e.price_before > 0 and after is not None:
            out.append((after - e.price_before) / e.price_before * 100)
    return out


def find_analogues(
    db: Session,
    event_type: str,
    direction: str | None = None,
    regime: str | None = None,
    stock_id: int | None = None,
    limit: int = 500,
) -> AnalogueResult:
    q = db.query(HistoricalEvent).filter(HistoricalEvent.event_type == event_type)
    if direction:
        q = q.filter(HistoricalEvent.direction == direction)
    if regime:
        q = q.filter(HistoricalEvent.regime == regime)
    if stock_id is not None:
        q = q.filter(HistoricalEvent.stock_id == stock_id)

    events = q.order_by(HistoricalEvent.event_timestamp.desc()).limit(limit).all()

    horizons = []
    for horizon, field_name in _HORIZON_FIELDS.items():
        returns = _returns_for_horizon(events, field_name)
        if returns:
            wins = sum(1 for r in returns if r > 0)
            horizons.append(HorizonStats(
                horizon=horizon, sample_count=len(returns),
                win_rate_pct=round(wins / len(returns) * 100, 1),
                median_return_pct=round(_median(returns), 2),
            ))
        else:
            horizons.append(HorizonStats(horizon, 0, None, None))

    return AnalogueResult(
        event_type=event_type, direction=direction,
        total_samples=len(events), horizons=horizons,
    )
