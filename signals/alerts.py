"""
Alert evaluation engine (MarketPulse AI Phase 5).

An Alert's `condition` is a flat dict of Django-style lookups
(`{"score__gt": 80, "volume_score__gt": 2}`) checked against a stock's
latest composite Signal — every key must match for the alert to fire
(AND-composed, per spec §29's example). Evaluation is a deterministic
comparison against real Signal columns, not an LLM call — there's
nothing here an LLM would do better than `operator.gt`.
"""
from __future__ import annotations
import operator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import Alert, AlertTrigger, Signal, SignalDirection
from signals.queries import latest_signal_per_stock
from utils.logger import get_logger

logger = get_logger("alerts")

# Only these Signal columns are queryable — an alert can't reach into
# arbitrary DB state, just the composite score the user can actually see.
_ALLOWED_FIELDS = {
    "score", "confidence", "catalyst_score", "technical_score",
    "momentum_score", "volume_score", "historical_score", "regime_score",
    "risk_score", "direction",
}
_OPERATORS = {
    "gt": operator.gt, "gte": operator.ge,
    "lt": operator.lt, "lte": operator.le,
    "eq": operator.eq,
}


def validate_condition(condition: dict) -> str | None:
    """Returns an error message if the condition is malformed, else None."""
    if not condition:
        return "condition cannot be empty"
    for key in condition:
        field_name, _, suffix = key.rpartition("__")
        if not field_name or suffix not in _OPERATORS:
            return f"invalid condition key '{key}' — expected '<field>__<gt|gte|lt|lte|eq>'"
        if field_name not in _ALLOWED_FIELDS:
            return f"unknown field '{field_name}' — allowed: {sorted(_ALLOWED_FIELDS)}"
    return None


def _condition_matches(signal: Signal, condition: dict) -> dict | None:
    """Returns the matched field->value snapshot if every condition key
    matches, else None. Fails closed on anything malformed or missing."""
    matched: dict = {}
    for key, threshold in condition.items():
        field_name, _, suffix = key.rpartition("__")
        if not field_name or suffix not in _OPERATORS or field_name not in _ALLOWED_FIELDS:
            return None
        value = getattr(signal, field_name, None)
        if field_name == "direction":
            value = value.value if isinstance(value, SignalDirection) else value
        if value is None:
            return None
        if not _OPERATORS[suffix](value, threshold):
            return None
        matched[field_name] = value
    return matched


@dataclass
class TriggerEvent:
    alert_id: int
    alert_name: str
    symbol: str
    matched_values: dict
    signal_id: int | None = None


@dataclass
class EvaluationSummary:
    alerts_checked: int
    triggers: list[TriggerEvent] = field(default_factory=list)


def evaluate_alerts(db: Session, notifier=None, timeframe: str = "1d") -> EvaluationSummary:
    """Runs every active Alert against the latest composite Signal per
    stock, records an AlertTrigger row for each match, and optionally
    notifies via `notifier` (anything with a `.send(text)` method — e.g.
    utils.telegram_alerts.TelegramAlerter; a no-op if not configured).

    `timeframe` selects which bar-size signals to evaluate against
    (docs/intraday_gaps.md §5) — defaults to "1d" so existing daily-
    cadence alert rules keep behaving exactly as before; an intraday
    scheduler job would pass e.g. "15m" explicitly."""
    alerts = db.query(Alert).filter(Alert.is_active == True).all()  # noqa: E712
    events: list[TriggerEvent] = []

    for alert in alerts:
        q = latest_signal_per_stock(db, timeframe=timeframe)
        if alert.stock_id is not None:
            q = q.filter(Signal.stock_id == alert.stock_id)

        for signal, symbol in q.all():
            matched = _condition_matches(signal, alert.condition)
            if matched is None:
                continue
            db.add(AlertTrigger(
                alert_id=alert.id, stock_id=signal.stock_id, signal_id=signal.id,
                matched_values=matched,
            ))
            alert.triggered_at = datetime.now(timezone.utc)
            events.append(TriggerEvent(
                alert_id=alert.id, alert_name=alert.name, symbol=symbol,
                matched_values=matched, signal_id=signal.id,
            ))

    db.commit()

    if events and notifier is not None and getattr(notifier, "enabled", False):
        lines = [f"\U0001F514 <b>{len(events)} alert(s) triggered</b>"]
        for e in events[:10]:
            lines.append(f"{e.alert_name}: {e.symbol} — {e.matched_values}")
        notifier.send("\n".join(lines))

    logger.info(f"Alert evaluation: {len(alerts)} active alerts checked, {len(events)} triggers")
    return EvaluationSummary(alerts_checked=len(alerts), triggers=events)
